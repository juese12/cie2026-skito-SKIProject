package xiangshan.backend.fu.vector

import chisel3._
import chisel3.util._
import chiseltest._
import org.chipsalliance.cde.config.Parameters
import xiangshan._
import xiangshan.backend.fu.{FuConfig, FuncUnitCtrlInput, FuncUnitDataInput}
import xiangshan.backend.fu.vector.Bundles.VConfig
import xiangshan.backend.fu.wrapper.VIMacU
import yunsuan.VimacType

/** Mirrors ExeUnit's fixed-time external control/data pipe with ready high. */
class VDotIntegrationHarness(implicit p: Parameters) extends XSModule {
  private val cfg = FuConfig.VimacCfg
  val io = IO(new Bundle {
    val valid = Input(Bool())
    val cancel = Input(Bool())
    val op = Input(UInt(9.W))
    val tag = Input(UInt(6.W))
    val vs1 = Input(UInt(128.W))
    val vs2 = Input(UInt(128.W))
    val oldVd = Input(UInt(128.W))
    val mask = Input(UInt(128.W))
    val vxrm = Input(UInt(2.W))
    val config = Input(new VConfig)
    val vm = Input(Bool())
    val vstart = Input(UInt(8.W))
    val v0Dest = Input(Bool())
    val outValid = Output(Bool())
    val outTag = Output(UInt(8.W))
    val result = Output(UInt(128.W))
    val illegal = Output(Bool())
    val saturated = Output(Bool())
    val vecWen = Output(Bool())
    val v0Wen = Output(Bool())
  })
  val fu = Module(new VIMacU(cfg))
  val ctrl = WireInit(0.U.asTypeOf(new FuncUnitCtrlInput(cfg)))
  ctrl.fuOpType := io.op
  ctrl.robIdx.value := io.tag
  ctrl.pdest := io.tag
  ctrl.vecWen.get := !io.v0Dest
  ctrl.v0Wen.get := io.v0Dest
  ctrl.vpu.get.connectVType(io.config.vtype)
  ctrl.vpu.get.vm := io.vm
  ctrl.vpu.get.vstart := io.vstart
  ctrl.vpu.get.lastUop := true.B
  val data = WireInit(0.U.asTypeOf(new FuncUnitDataInput(cfg)))
  data.src(0) := io.vs1
  data.src(1) := io.vs2
  data.src(2) := io.oldVd
  data.src(cfg.maskSrcIdx) := io.mask
  data.src(cfg.vconfigIdx) := io.config.asUInt
  val ctrlPipe = ctrl +: Seq.fill(2)(Reg(chiselTypeOf(ctrl)))
  val dataPipe = data +: Seq.fill(2)(Reg(chiselTypeOf(data)))
  val validPipe = (io.valid && !io.cancel) +: Seq.fill(2)(RegInit(false.B))
  for (i <- 1 to 2) {
    ctrlPipe(i) := ctrlPipe(i - 1)
    dataPipe(i) := dataPipe(i - 1)
    validPipe(i) := validPipe(i - 1) && !io.cancel
  }
  fu.io.in.bits := 0.U.asTypeOf(fu.io.in.bits)
  fu.io.in.valid := validPipe.head
  fu.io.in.bits.ctrl := ctrl
  fu.io.in.bits.data := data
  for (i <- 0 to 2) {
    fu.io.in.bits.ctrlPipe.get(i) := ctrlPipe(i)
    fu.io.in.bits.dataPipe.get(i) := dataPipe(i)
    fu.io.in.bits.validPipe.get(i) := validPipe(i)
  }
  fu.io.flush.valid := io.cancel
  fu.io.flush.bits := 0.U.asTypeOf(fu.io.flush.bits)
  fu.io.out.ready := true.B
  fu.io.vxrm.foreach(_ := io.vxrm)
  fu.io.frm.foreach(_ := 0.U)
  io.outValid := fu.io.out.valid
  io.outTag := fu.io.out.bits.ctrl.pdest
  io.result := fu.io.out.bits.res.data
  io.illegal := fu.io.out.bits.ctrl.exceptionVec.get(ExceptionNO.illegalInstr)
  io.saturated := fu.io.out.bits.res.vxsat.get.asBool
  io.vecWen := fu.io.out.bits.ctrl.vecWen.get
  io.v0Wen := fu.io.out.bits.ctrl.v0Wen.get
}

class VDotIntegrationTest extends XSTester {
  behavior of "VIMacU vdot integration"
  it should "align mixed operations, tags, full writes, runtime legality and canceled operations" in {
    val testConfig = config.alterPartial {
      case utility.LogUtilsOptionsKey => utility.LogUtilsOptions(
        enableDebug = false, enablePerf = false, fpgaPlatform = true)
    }
    test(new VDotIntegrationHarness()(testConfig)).withAnnotations(Seq(VerilatorBackendAnnotation, WriteVcdAnnotation)) { dut =>
      case class Expected(tag: Int, data: BigInt, illegal: Boolean, v0: Boolean)
      val byteOnes = BigInt("01" * 16, 16)
      val byteTwos = BigInt("02" * 16, 16)
      var pending = List.fill[Option[Expected]](2)(None)
      var issued = 0
      var checked = 0
      dut.io.valid.poke(false.B)
      dut.io.cancel.poke(false.B)
      dut.io.op.poke(VdotOpType.vdot)
      dut.io.tag.poke(1.U)
      dut.io.vs1.poke(byteOnes.U)
      dut.io.vs2.poke(byteTwos.U)
      dut.io.oldVd.poke(((BigInt(1) << 128) - 1).U)
      dut.io.mask.poke(((BigInt(1) << 128) - 1).U)
      dut.io.vxrm.poke(0.U)
      dut.io.vm.poke(true.B)
      dut.io.vstart.poke(0.U)
      dut.io.v0Dest.poke(false.B)
      dut.io.config.vtype.illegal.poke(false.B)
      dut.io.config.vtype.vta.poke(false.B)
      dut.io.config.vtype.vma.poke(false.B)
      dut.io.config.vtype.vsew.poke(0.U)
      dut.io.config.vtype.vlmul.poke(0.U)
      dut.io.config.vl.poke(8.U)
      dut.clock.step(3)

      def tick(input: Option[Expected], op: BigInt = 0x160, vl: Int = 8,
               vm: Boolean = true, start: Int = 0, cancel: Boolean = false,
               old: BigInt = (BigInt(1) << 128) - 1): Unit = {
        dut.io.valid.poke(input.nonEmpty.B)
        dut.io.cancel.poke(cancel.B)
        dut.io.op.poke(op.U)
        dut.io.config.vl.poke(vl.U)
        dut.io.vm.poke(vm.B)
        dut.io.vstart.poke(start.U)
        dut.io.oldVd.poke(old.U)
        dut.io.tag.poke(input.map(_.tag).getOrElse(1).U)
        dut.io.v0Dest.poke(input.exists(_.v0).B)
        if (cancel) pending = List(None, None)
        dut.clock.step()
        pending = input.filter(_ => !cancel) :: pending.take(1)
        pending(1) match {
          case Some(e) =>
            dut.io.outValid.expect(true.B)
            dut.io.outTag.expect(e.tag.U)
            dut.io.illegal.expect(e.illegal.B)
            dut.io.saturated.expect(false.B)
            dut.io.vecWen.expect((!e.v0).B)
            dut.io.v0Wen.expect(e.v0.B)
            if (!e.illegal) dut.io.result.expect(e.data.U)
            checked += 1
          case None => dut.io.outValid.expect(false.B)
        }
        if (input.nonEmpty) issued += 1
      }
      for (i <- 1 to 16) {
        val isMul = i % 2 == 0
        dut.io.config.vtype.vta.poke((!isMul && i % 3 == 0).B)
        dut.io.config.vtype.vma.poke((i % 4 == 0).B)
        val result = if (isMul) (byteTwos & ((BigInt(1) << 64) - 1)) else BigInt(16)
        // vl=8/tu preserves old upper bytes for ordinary vmul, never for dot.
        tick(Some(Expected(i, result, false, i % 5 == 0)),
          if (isMul) VimacType.vmul.litValue else BigInt(0x160), old = 0)
        if (i % 3 == 0) tick(None)
      }
      for (vl <- Seq(0, 1, 7, 9, 16)) tick(Some(Expected(20 + vl, 0, true, false)), vl = vl)
      tick(Some(Expected(40, 0, true, false)), vm = false)
      tick(Some(Expected(41, 0, true, false)), start = 1)
      tick(None)
      tick(None)
      tick(Some(Expected(42, 16, false, false)))
      tick(None, cancel = true)
      tick(None)
      tick(Some(Expected(43, 16, false, true)))
      tick(None)
      tick(None)
      checked shouldBe issued - 1
    }
  }

  it should "preserve randomized mixed traffic and ordinary mask tail multiply accumulate and saturation" in {
    val testConfig = config.alterPartial {
      case utility.LogUtilsOptionsKey => utility.LogUtilsOptions(
        enableDebug = false, enablePerf = false, fpgaPlatform = true)
    }
    test(new VDotIntegrationHarness()(testConfig)).withAnnotations(Seq(VerilatorBackendAnnotation, WriteVcdAnnotation)) { dut =>
      val random = new scala.util.Random(0x49534f4cL)
      val full = (BigInt(1) << 128) - 1
      case class Expected(tag: Int, result: BigInt, saturated: Boolean)
      var pending = List.fill[Option[Expected]](2)(None)
      var checked = 0
      var issued = 0
      var killed = 0

      def signed(x: BigInt, width: Int): BigInt =
        if (x.testBit(width - 1)) x - (BigInt(1) << width) else x

      def tick(kind: String, sew: Int = 8, valid: Boolean = true, cancel: Boolean = false,
               forceSat: Boolean = false): Unit = {
        val dot = kind == "dot"
        val width = if (dot) 8 else sew
        val count = 128 / width
        val elemMask = (BigInt(1) << width) - 1
        val a = if (forceSat) BigInt("80" * 16, 16) else BigInt(128, random)
        val b = if (forceSat) a else BigInt(128, random)
        val old = BigInt(128, random)
        val mask = BigInt(128, random)
        val vl = if (dot) 8 else if (forceSat) count else random.nextInt(count + 1)
        val vm = dot || forceSat || random.nextBoolean()
        val ta = random.nextBoolean()
        val ma = random.nextBoolean()
        val tag = issued % 63 + 1
        val op = kind match {
          case "dot" => VdotOpType.vdot
          case "mul" => VimacType.vmul
          case "macc" => VimacType.vmacc
          case "madd" => VimacType.vmadd
          case "nmsac" => VimacType.vnmsac
          case "smul" => VimacType.vsmul
        }
        var sat = false
        val result = if (dot) {
          (0 until 8).map { i =>
            signed((a >> (8 * i)) & 255, 8) * signed((b >> (8 * i)) & 255, 8)
          }.sum & BigInt("ffffffff", 16)
        } else {
          (0 until count).map { i =>
            val x = signed((a >> (width * i)) & elemMask, width)
            val y = signed((b >> (width * i)) & elemMask, width)
            val z = (old >> (width * i)) & elemMask
            val active = i < vl && (vm || mask.testBit(i))
            val product = kind match {
              case "mul" => x * y
              case "macc" => x * y + z
              case "madd" => x * signed(z, width) + y
              case "nmsac" => z - x * y
              case "smul" =>
                val overflow = x == -(BigInt(1) << (width - 1)) && x == y
                if (active && overflow) sat = true
                if (overflow) (BigInt(1) << (width - 1)) - 1 else (x * y) >> (width - 1)
            }
            // vstart >= vl preserves the whole destination, even with ta/ma.
            val value = if (vl == 0) z else if (active) product & elemMask
              else if ((i >= vl && ta) || (i < vl && ma)) elemMask else z
            value << (width * i)
          }.foldLeft(BigInt(0))(_ | _)
        }
        dut.io.valid.poke(valid.B)
        dut.io.cancel.poke(cancel.B)
        dut.io.op.poke(op)
        dut.io.tag.poke(tag.U)
        dut.io.vs1.poke(a.U)
        dut.io.vs2.poke(b.U)
        dut.io.oldVd.poke(old.U)
        dut.io.mask.poke(mask.U)
        dut.io.vxrm.poke(2.U) // RDN: signed arithmetic shift in the oracle.
        dut.io.vm.poke(vm.B)
        dut.io.vstart.poke(0.U)
        dut.io.v0Dest.poke(false.B)
        dut.io.config.vtype.illegal.poke(false.B)
        dut.io.config.vtype.vta.poke(ta.B)
        dut.io.config.vtype.vma.poke(ma.B)
        dut.io.config.vtype.vsew.poke(Integer.numberOfTrailingZeros(width / 8).U)
        dut.io.config.vtype.vlmul.poke(0.U)
        dut.io.config.vl.poke(vl.U)
        if (cancel) {
          killed += pending.take(1).count(_.nonEmpty)
          pending = List(None, None)
        }
        val input = if (valid && !cancel) Some(Expected(tag, result & full, sat)) else None
        dut.clock.step()
        pending = input :: pending.take(1)
        pending(1) match {
          case Some(e) =>
            dut.io.outValid.expect(true.B)
            dut.io.outTag.expect(e.tag.U)
            dut.io.illegal.expect(false.B)
            dut.io.result.expect(e.result.U)
            dut.io.saturated.expect(e.saturated.B)
            checked += 1
          case None => dut.io.outValid.expect(false.B)
        }
        if (input.nonEmpty) issued += 1
      }

      for (_ <- 0 until 3) tick("mul", valid = false)
      // Long homogeneous windows also supply switching/hold audit evidence.
      for (_ <- 0 until 32) tick("dot")
      for (_ <- 0 until 32) tick("mul", sew = 32)
      for (i <- 0 until 240) {
        val kinds = Seq("dot", "mul", "macc", "madd", "nmsac", "smul")
        tick(kinds(i % kinds.size), sew = Seq(8, 16, 32, 64)((i / 6) % 4))
        if (i % 11 == 0) tick("mul", valid = false)
        if (i % 37 == 0) tick("dot", valid = false, cancel = true)
      }
      tick("smul", forceSat = true)
      tick("dot")
      tick("smul", forceSat = true)
      for (_ <- 0 until 12) tick("mul", valid = false)
      checked shouldBe issued - killed
      println(s"isolation functional PASS: issued=$issued checked=$checked canceled=$killed seed=0x49534f4c")
    }
  }
}
