package xiangshan.backend.fu.vector

import chisel3._
import chiseltest._
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import scala.util.Random

class VDot8Test extends AnyFlatSpec with ChiselScalatestTester with Matchers {
  private def pack(bytes: Seq[Int], high: BigInt): BigInt =
    (high << 64) | bytes.zipWithIndex.map { case (b, i) => BigInt(b & 255) << (8 * i) }.reduce(_ | _)

  behavior of "VDot8"
  it should "produce exact signed sums with enabled stages, bubbles and poisoned upper bytes" in {
    test(new VDot8).withAnnotations(Seq(VerilatorBackendAnnotation, WriteVcdAnnotation)) { dut =>
      val random = new Random(0x56444f54L)
      val directed = Seq(
        (1 to 8, Seq.fill(8)(1)),
        (1 to 8, (1 to 8).reverse),
        ((1 to 8).map(-_), Seq.fill(8)(1)),
        (Seq.fill(8)(-128), Seq.fill(8)(-128)),
        (Seq.fill(8)(-128), Seq.fill(8)(127)),
        (Seq.fill(8)(127), Seq.fill(8)(127)),
        (Seq.fill(8)(0), Seq.fill(8)(-128))
      )
      val vectors = directed ++ Seq.fill(1000)(
        (Seq.fill(8)(random.nextInt(256) - 128), Seq.fill(8)(random.nextInt(256) - 128)))
      var stage1: Option[BigInt] = None
      var stage2: Option[BigInt] = None
      dut.io.enable.foreach(_.poke(false.B))
      dut.io.vs1.poke(0.U)
      dut.io.vs2.poke(0.U)
      dut.clock.step()
      for ((a, b) <- vectors) {
        // Model each enabled register independently, including simultaneous
        // advance, disabled holds and transfer without a new input.
        for (_ <- 0 until (if (random.nextBoolean()) 1 else 2)) {
          val en1 = random.nextInt(4) != 0
          val en2 = random.nextInt(4) != 0
          val sum = BigInt(a.zip(b).map { case (x, y) => x * y }.sum) & 0xffffffffL
          dut.io.vs1.poke(pack(a, BigInt(64, random)).U)
          dut.io.vs2.poke(pack(b, BigInt(64, random)).U)
          dut.io.enable(0).poke(en1.B)
          dut.io.enable(1).poke(en2.B)
          val next2 = if (en2) stage1 else stage2
          if (en1) stage1 = Some(sum)
          dut.clock.step()
          stage2 = next2
          stage2.foreach(v => dut.io.result.expect(v.U))
        }
      }
      // Explicit endpoint: 18 signed bits cannot hold this result.
      dut.io.vs1.poke(pack(Seq.fill(8)(-128), 0).U)
      dut.io.vs2.poke(pack(Seq.fill(8)(-128), 0).U)
      dut.io.enable(0).poke(true.B)
      dut.io.enable(1).poke(false.B)
      dut.clock.step()
      dut.io.enable(0).poke(false.B)
      dut.io.enable(1).poke(true.B)
      dut.clock.step()
      dut.io.result.expect(BigInt(131072).U)
    }
  }

  it should "hold a negative full-register result while disabled inputs keep changing" in {
    test(new VDot8).withAnnotations(Seq(VerilatorBackendAnnotation)) { dut =>
      dut.io.vs1.poke(pack(Seq.fill(8)(-128), 0).U)
      dut.io.vs2.poke(pack(Seq.fill(8)(127), 0).U)
      dut.io.enable(0).poke(true.B)
      dut.io.enable(1).poke(false.B)
      dut.clock.step()
      dut.io.enable(0).poke(false.B)
      dut.io.enable(1).poke(true.B)
      dut.clock.step()
      val expected = BigInt(-130048) & BigInt("ffffffff", 16)
      dut.io.result.expect(expected.U)
      dut.io.enable.foreach(_.poke(false.B))
      val random = new Random(0x484f4c44L)
      for (_ <- 0 until 96) {
        dut.io.vs1.poke(BigInt(128, random).U)
        dut.io.vs2.poke(BigInt(128, random).U)
        dut.clock.step()
        dut.io.result.expect(expected.U)
      }
      // Stage-one holds must preserve the products for a later transfer too.
      dut.io.enable(1).poke(true.B)
      dut.clock.step()
      dut.io.result.expect(expected.U)
    }
  }
}
