package xiangshan.backend.fu.vector

import chisel3._
import chisel3.util._

/** Two explicitly enabled stages: full signed products, then exact reduction.
  * The owner supplies stage enables from its control pipeline. Valid/flush and
  * destination tags remain in the existing vector execution interface.
  */
class VDot8 extends Module {
  val io = IO(new Bundle {
    val vs1 = Input(UInt(128.W))
    val vs2 = Input(UInt(128.W))
    val enable = Input(Vec(2, Bool()))
    val result = Output(UInt(128.W))
  })

  // Register enables alone do not isolate the combinational multipliers.
  // Only the low eight bytes are used; clamp them before multiplication.
  val isolatedVs1 = Mux(io.enable(0), io.vs1(63, 0), 0.U(64.W))
  val isolatedVs2 = Mux(io.enable(0), io.vs2(63, 0), 0.U(64.W))
  val products = Reg(Vec(8, SInt(16.W)))
  when(io.enable(0)) {
    for (i <- 0 until 8) {
      products(i) := isolatedVs1(8 * i + 7, 8 * i).asSInt *
        isolatedVs2(8 * i + 7, 8 * i).asSInt
    }
  }
  val pairs = (0 until 4).map(i => products(2 * i) +& products(2 * i + 1))
  val quads = (0 until 2).map(i => pairs(2 * i) +& pairs(2 * i + 1))
  val sum = RegEnable(quads(0) +& quads(1), io.enable(1))
  require(sum.getWidth == 19)
  val sum32 = Wire(SInt(32.W))
  sum32 := sum
  io.result := Cat(0.U(96.W), sum32.asUInt)
}
