package xiangshan

import chisel3._
import chisel3.util._
import chiseltest._
import org.chipsalliance.cde.config.Parameters
import xiangshan.backend.Bundles.DecodedInst
import xiangshan.backend.decode._
import xiangshan.backend.decode.isa.bitfield.XSInstBitFields

/** Exercises the actual decode tables, uop count generator and legality logic. */
class VDotDecodeHarness(implicit p: Parameters) extends Module {
  val io = IO(new Bundle {
    val inst = Input(UInt(32.W))
    val sew = Input(UInt(2.W))
    val lmul = Input(UInt(3.W))
    val vstart = Input(UInt(8.W))
    val vill = Input(Bool())
    val recognized = Output(Bool())
    val op = Output(UInt(9.W))
    val numUops = Output(UInt(8.W))
    val numWB = Output(UInt(8.W))
    val complex = Output(Bool())
    val illegal = Output(Bool())
  })
  val fields = io.inst.asTypeOf(new XSInstBitFields)
  val decoded = WireInit(0.U.asTypeOf(new DecodedInst))
  decoded.decode(io.inst, VecDecoder.table)
  decoded.lsrc(0) := fields.RS1
  decoded.lsrc(1) := fields.RS2
  decoded.ldest := fields.RD
  val uops = Module(new UopInfoGen)
  uops.io.in.preInfo := 0.U.asTypeOf(uops.io.in.preInfo)
  uops.io.in.preInfo.isVecArith := fields.isVecArith
  uops.io.in.preInfo.typeOfSplit := decoded.uopSplitType
  uops.io.in.preInfo.vsew := io.sew
  uops.io.in.preInfo.vlmul := io.lmul
  val exceptions = Module(new VecExceptionGen)
  exceptions.io.inst := io.inst
  exceptions.io.decodedInst := decoded
  exceptions.io.vtype := 0.U.asTypeOf(exceptions.io.vtype)
  exceptions.io.vtype.vsew := io.sew
  exceptions.io.vtype.vlmul := io.lmul
  exceptions.io.vtype.illegal := io.vill
  exceptions.io.vstart := io.vstart
  io.recognized := XVDot.VDOT_VV === io.inst
  io.op := decoded.fuOpType
  io.numUops := uops.io.out.uopInfo.numOfUop
  io.numWB := uops.io.out.uopInfo.numOfWB
  io.complex := uops.io.out.isComplex
  io.illegal := exceptions.io.illegalInst
}

class VDotDecodeTest extends XSTester {
  behavior of "vdot decode"
  it should "use a unique encoding across all active decode tables" in {
    val tables = XDecode.table ++ FpDecode.table ++ BitmanipDecode.table ++
      ScalarCryptoDecode.table ++ XSTrapDecode.table ++ CBODecode.table ++
      SvinvalDecode.table ++ HypervisorDecode.table ++ VecDecoder.table ++
      ZicondDecode.table ++ ZimopDecode.table ++ ZfaDecode.table
    val dot = XVDot.VDOT_VV
    val overlaps = tables.filter { case (pat, _) =>
      ((pat.value ^ dot.value) & pat.mask & dot.mask) == 0
    }
    overlaps.length shouldBe 1
    overlaps.head._1 shouldBe dot
    (VdotOpType.vdot.litValue >> 7) should not be BigInt(0)
  }
  it should "emit one uop and reject unsupported static configurations" in {
    test(new VDotDecodeHarness).withAnnotations(Seq(VerilatorBackendAnnotation)) { dut =>
      dut.io.sew.poke(0.U)
      dut.io.lmul.poke(0.U)
      dut.io.vstart.poke(0.U)
      dut.io.vill.poke(false.B)
      for (vd <- Seq(0, 1, 30, 31); vs1 <- Seq(0, 8, 31); vs2 <- Seq(0, 9, 31)) {
        val word = BigInt(0x0200200b) | (BigInt(vs2) << 20) | (BigInt(vs1) << 15) | (BigInt(vd) << 7)
        dut.io.inst.poke(word.U)
        dut.io.recognized.expect(true.B)
        dut.io.op.expect(0x160.U)
        dut.io.numUops.expect(1.U)
        dut.io.numWB.expect(1.U)
        dut.io.complex.expect(true.B)
        dut.io.illegal.expect(false.B)
      }
      dut.io.inst.poke(0x0294250b.U)
      for (sew <- 1 to 3) {
        dut.io.sew.poke(sew.U)
        dut.io.illegal.expect(true.B)
      }
      dut.io.sew.poke(0.U)
      for (lmul <- 1 to 7) {
        dut.io.lmul.poke(lmul.U)
        dut.io.numUops.expect(1.U)
        dut.io.numWB.expect(1.U)
        dut.io.illegal.expect(true.B)
      }
      dut.io.lmul.poke(0.U)
      dut.io.vstart.poke(1.U)
      dut.io.illegal.expect(true.B)
      dut.io.vstart.poke(0.U)
      dut.io.vill.poke(true.B)
      dut.io.illegal.expect(true.B)
      dut.io.vill.poke(false.B)
      dut.io.inst.poke(0x0094250b.U) // vm=0
      dut.io.illegal.expect(true.B)
      for (word <- Seq(0x0294252bL, 0x0694250bL, 0x0294150bL)) {
        dut.io.inst.poke(word.U)
        dut.io.recognized.expect(false.B)
      }
    }
  }
}

/** Exercise the actual registered complex splitter, not a copied expression. */
class VDotSplitHarness(implicit p: Parameters) extends Module {
  val io = IO(new Bundle {
    val inst = Input(UInt(32.W))
    val valid = Input(Bool())
    val ready = Output(Bool())
    val outValid = Output(Bool())
    val srcType = Output(Vec(3, UInt(4.W)))
    val lsrc = Output(Vec(3, UInt(6.W)))
    val ldest = Output(UInt(6.W))
  })
  val fields = io.inst.asTypeOf(new XSInstBitFields)
  val decoded = WireInit(0.U.asTypeOf(new DecodedInst))
  decoded.decode(io.inst, VecDecoder.table)
  decoded.instr := io.inst
  decoded.lsrc(0) := fields.RS1
  decoded.lsrc(1) := fields.RS2
  decoded.lsrc(2) := fields.RD
  decoded.ldest := fields.RD
  decoded.vpu.vm := fields.VM
  val uops = Module(new UopInfoGen)
  uops.io.in.preInfo := 0.U.asTypeOf(uops.io.in.preInfo)
  uops.io.in.preInfo.isVecArith := fields.isVecArith
  uops.io.in.preInfo.typeOfSplit := decoded.uopSplitType
  val split = Module(new DecodeUnitComp)
  split.io.redirect := false.B
  split.io.csrCtrl := 0.U.asTypeOf(split.io.csrCtrl)
  split.io.vtypeBypass := 0.U.asTypeOf(split.io.vtypeBypass)
  split.io.in.valid := io.valid
  split.io.in.bits.simpleDecodedInst := decoded
  split.io.in.bits.uopInfo := uops.io.out.uopInfo
  split.io.out.complexDecodedInsts.foreach(_.ready := true.B)
  io.ready := split.io.in.ready
  val out = split.io.out.complexDecodedInsts.head
  io.outValid := out.valid
  for (i <- 0 until 3) {
    io.srcType(i) := out.bits.srcType(i)
    io.lsrc(i) := out.bits.lsrc(i)
  }
  io.ldest := out.bits.ldest
}

class VDotSplitTest extends XSTester {
  behavior of "vdot complex split old destination elimination"
  it should "remove only the third dot source and preserve true aliases and ordinary MAC" in {
    val testConfig = config.alterPartial {
      case utility.LogUtilsOptionsKey => utility.LogUtilsOptions(
        enableDebug = false, enablePerf = false, fpgaPlatform = true)
    }
    test(new VDotSplitHarness()(testConfig)).withAnnotations(Seq(VerilatorBackendAnnotation)) { dut =>
      dut.io.valid.poke(false.B)
      dut.io.inst.poke(0.U)
      dut.clock.step(2)
      def check(word: BigInt, vd: Int, vs1: Int, vs2: Int, oldType: BigInt): Unit = {
        var limit = 0
        while (!dut.io.ready.peek().litToBoolean && limit < 10) { dut.clock.step(); limit += 1 }
        dut.io.ready.expect(true.B)
        dut.io.inst.poke(word.U)
        dut.io.valid.poke(true.B)
        dut.clock.step()
        dut.io.valid.poke(false.B)
        limit = 0
        while (!dut.io.outValid.peek().litToBoolean && limit < 10) { dut.clock.step(); limit += 1 }
        dut.io.outValid.expect(true.B)
        dut.io.srcType(0).expect(SrcType.vp)
        dut.io.srcType(1).expect(SrcType.vp)
        dut.io.srcType(2).expect(oldType.U)
        dut.io.lsrc(0).expect(vs1.U)
        dut.io.lsrc(1).expect(vs2.U)
        dut.io.ldest.expect(vd.U)
        dut.clock.step(2)
      }
      for (vd <- Seq(0, 8, 9, 31); vs1 <- Seq(0, 8, 31); vs2 <- Seq(0, 9, 31)) {
        val word = BigInt(0x0200200b) | (BigInt(vs2) << 20) | (BigInt(vs1) << 15) | (BigInt(vd) << 7)
        check(word,vd,vs1,vs2,SrcType.no.litValue)
      }
      // vmacc.vv v10,v9,v8: an actual old-destination arithmetic dependency.
      check(BigInt(0xb6942557L),10,8,9,SrcType.vp.litValue)
    }
  }
}
