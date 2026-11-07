package xiangshan.backend.fu.wrapper

import org.chipsalliance.cde.config.Parameters
import chisel3._
import chisel3.util._
import utility.XSError
import xiangshan.backend.fu.FuConfig
import xiangshan.backend.fu.vector.Bundles.VSew
import xiangshan.backend.fu.vector.utils.VecDataSplitModule
import xiangshan.backend.fu.vector.{Mgu, Utils, VecPipedFuncUnit, VecSrcTypeModule, VDot8}
import xiangshan.VdotOpType
import xiangshan.ExceptionNO
import yunsuan.VialuFixType
import yunsuan.encoding.Opcode.VimacOpcode
import yunsuan.encoding.{VdType, Vs1IntType, Vs2IntType}
import yunsuan.{OpType, VimacType}
import yunsuan.vector.mac.VIMac64b

class VIMacSrcTypeModule extends VecSrcTypeModule {

  private val opcode  = VimacType.getOpcode(fuOpType)
  private val vs2Sign = VimacType.vs2Sign(fuOpType)
  private val vs1Sign = VimacType.vs1Sign(fuOpType)
  private val vdSign  = VimacType.vdSign(fuOpType)
  private val format  = VimacType.getFormat(fuOpType)
  private val widen   = format === VimacType.FMT.VVW

  private val vs2IntType = Cat(0.U(1.W), vs2Sign)
  private val vs1IntType = Cat(0.U(1.W), vs1Sign)
  private val vdIntType  = Cat(0.U(1.W),  vdSign)

  private val vsewX2 = vsew + 1.U

  private val vs2Type = Cat(vs2IntType, vsew)
  private val vs1Type = Cat(vs1IntType, vsew)
  private val vdType  = Cat( vdIntType, Mux(widen, vsewX2, vsew))

  private val widenIllegal = widen && vsewX2 === VSew.e8

  io.out.illegal := widenIllegal
  io.out.vs2Type := vs2Type
  io.out.vs1Type := vs1Type
  io.out.vdType  := vdType
}

class VIMacU(cfg: FuConfig)(implicit p: Parameters) extends VecPipedFuncUnit(cfg) {
  XSError(io.in.valid && io.in.bits.ctrl.fuOpType === VimacType.dummy, "VialuF OpType not supported")

  // params alias
  private val dataWidth = cfg.destDataBits
  private val dataWidthOfDataModule = 64
  private val numVecModule = dataWidth / dataWidthOfDataModule
  require(dataWidth == 128 && latency == 2 && latdiff == 0,
    "vdot v0.1 requires the existing 128-bit, two-stage Vimac interface")

  // io alias
  private val inIsVdot = fuOpType === VdotOpType.vdot
  // Keep ordinary VIMac's fixed-time fire contract. Its internal fireS1
  // completes an older multiply even while a younger dot enters this unit.
  private val macInputActive = io.in.valid && !inIsVdot
  private val macFuOpType = Mux(macInputActive, fuOpType, VimacType.vmul)
  private val opcode  = VimacType.getOpcode(macFuOpType)
  private val format  = VimacType.getFormat(macFuOpType)
  private val widen   = format === VimacType.FMT.VVW
  private val exchangeVs2Vd = VimacOpcode.overWriteMultiplicand(opcode)

  // modules
  private val typeMod = Module(new VIMacSrcTypeModule)
  private val vs2Split = Module(new VecDataSplitModule(dataWidth, dataWidthOfDataModule))
  private val vs1Split = Module(new VecDataSplitModule(dataWidth, dataWidthOfDataModule))
  private val oldVdSplit  = Module(new VecDataSplitModule(dataWidth, dataWidthOfDataModule))
  private val vimacs = Seq.fill(numVecModule)(Module(new VIMac64b))
  private val mgu = Module(new Mgu(dataWidth))
  private val vdot = Module(new VDot8)
  vdot.io.vs1 := vs1
  vdot.io.vs2 := vs2
  vdot.io.enable(0) := regEnable(1) && inIsVdot
  // Stage two belongs to the instruction in stage one, NOT the current input.
  vdot.io.enable(1) := regEnable(2) && ctrlVec(1).fuOpType === VdotOpType.vdot

  /**
    * [[typeMod]]'s in connection
    */
  typeMod.io.in.fuOpType := macFuOpType
  typeMod.io.in.vsew := Mux(macInputActive, vsew, 0.U)
  typeMod.io.in.isReverse := macInputActive && isReverse
  typeMod.io.in.isExt := macInputActive && isExt
  typeMod.io.in.isDstMask := macInputActive && vecCtrl.isDstMask
  typeMod.io.in.isMove := macInputActive && isMove

  /**
    * In connection of [[vs2Split]], [[vs1Split]] and [[oldVdSplit]]
    */
  vs2Split.io.inVecData := Mux(macInputActive, vs2, 0.U(dataWidth.W))
  vs1Split.io.inVecData := Mux(macInputActive, vs1, 0.U(dataWidth.W))
  oldVdSplit.io.inVecData := Mux(macInputActive, oldVd, 0.U(dataWidth.W))

  /**
    * [[vimacs]]'s in connection
    */
  // Vec(vs2(31,0), vs2(63,32), vs2(95,64), vs2(127,96)) ==>
  // Vec(
  //   Cat(vs2(95,64),  vs2(31,0)),
  //   Cat(vs2(127,96), vs2(63,32)),
  // )
  private val vs2GroupedVec: Vec[UInt] = VecInit(vs2Split.io.outVec32b.zipWithIndex.groupBy(_._2 % 2).map(x => x._1 -> x._2.map(_._1)).values.map(x => Cat(x.reverse)).toSeq)
  private val vs1GroupedVec: Vec[UInt] = VecInit(vs1Split.io.outVec32b.zipWithIndex.groupBy(_._2 % 2).map(x => x._1 -> x._2.map(_._1)).values.map(x => Cat(x.reverse)).toSeq)

  private val vs2VecUsed: Vec[UInt] = Mux(widen, vs2GroupedVec, vs2Split.io.outVec64b)
  private val vs1VecUsed: Vec[UInt] = Mux(widen, vs1GroupedVec, vs1Split.io.outVec64b)
  private val oldVdVecUsed: Vec[UInt] = WireInit(oldVdSplit.io.outVec64b)

  vimacs.zipWithIndex.foreach {
    case (mod, i) =>
      mod.io.fire        := macInputActive
      mod.io.info.vm     := macInputActive && vm
      mod.io.info.ma     := macInputActive && vma
      mod.io.info.ta     := macInputActive && vta
      mod.io.info.vlmul  := Mux(macInputActive, vlmul, 0.U)
      mod.io.info.vl     := Mux(macInputActive, srcVConfig.vl, 0.U)
      mod.io.info.vstart := Mux(macInputActive, vstart, 0.U)
      mod.io.info.uopIdx := Mux(macInputActive, vuopIdx, 0.U)
      mod.io.info.vxrm   := Mux(macInputActive, vxrm, 0.U)
      mod.io.srcType(0)  := typeMod.io.out.vs2Type
      mod.io.srcType(1)  := typeMod.io.out.vs1Type
      mod.io.vdType      := typeMod.io.out.vdType
      mod.io.vs1         := vs1VecUsed(i)
      mod.io.vs2         := Mux(!exchangeVs2Vd, vs2VecUsed(i), oldVdVecUsed(i))
      mod.io.oldVd       := Mux(!exchangeVs2Vd, oldVdVecUsed(i), vs2VecUsed(i))
      mod.io.highHalf    := VimacOpcode.highHalf(opcode)
      mod.io.isMacc      := VimacOpcode.isMacc(opcode)
      mod.io.isSub       := VimacOpcode.isSub(opcode)
      mod.io.widen       := widen
      mod.io.isFixP      := VimacOpcode.isFixP(opcode)
  }

  /**
    * [[mgu]]'s in connection
    */
  private val outVd = Cat(vimacs.reverse.map(_.io.vd))
  private val outFormat = VimacType.getFormat(outCtrl.fuOpType)
  private val outWiden = outFormat === VimacType.FMT.VVW
  private val outVxsat = Cat(vimacs.reverse.map(_.io.vxsat))

  private val outEew = Mux(outWiden, outVecCtrl.vsew + 1.U, outVecCtrl.vsew)
  mgu.io.in.vd := outVd
  mgu.io.in.oldVd := outOldVd
  mgu.io.in.mask := outSrcMask
  mgu.io.in.info.ta := outVecCtrl.vta
  mgu.io.in.info.ma := outVecCtrl.vma
  mgu.io.in.info.vl := outVl
  mgu.io.in.info.vlmul := outVecCtrl.vlmul
  mgu.io.in.info.valid := io.out.valid
  mgu.io.in.info.vstart := outVecCtrl.vstart
  mgu.io.in.info.eew := outEew
  mgu.io.in.info.vsew := outVecCtrl.vsew
  mgu.io.in.info.vdIdx := outVecCtrl.vuopIdx
  mgu.io.in.info.narrow := 0.B
  mgu.io.in.info.dstMask := 0.B
  mgu.io.in.isIndexedVls := false.B

  private val outIsVdot = outCtrl.fuOpType === VdotOpType.vdot
  private val vdotIllegal = outVConfig.vtype.illegal ||
    outVConfig.vtype.vsew =/= 0.U || outVConfig.vtype.vlmul =/= 0.U ||
    outVl =/= 8.U || !outVm || outVstart =/= 0.U

  // Dot writes the whole register independently of mask/tail merge policies.
  io.out.bits.res.data := Mux(outIsVdot, vdot.io.result, mgu.io.out.vd)
  io.out.bits.res.vxsat.get := !outIsVdot && (outVxsat & mgu.io.out.active).orR
  io.out.bits.ctrl.exceptionVec.get(ExceptionNO.illegalInstr) :=
    outVstart =/= 0.U || Mux(outIsVdot, vdotIllegal, mgu.io.out.illegal)
}
