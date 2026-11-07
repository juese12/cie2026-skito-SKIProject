NAME = cie2026-e2e-diagnosis
SRCS = main.c bench.S runtime-config.S
MARCH ?= rv64gcv_zba
DIAG_BATCHES ?= 32
CFLAGS += -fno-tree-vectorize -fno-tree-slp-vectorize -DVDOT_BENCH_RANDOM=0
CFLAGS += -DVDOT_BENCH_RUNTIME_ORDER=1 -DDIAG_BATCHES=$(DIAG_BATCHES)
include $(AM_HOME)/Makefile.app
