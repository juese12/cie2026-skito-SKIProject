NAME = cie2026-e2e-controlled
SRCS = main.c bench.S
MARCH ?= rv64gcv_zba
CFLAGS += -fno-tree-vectorize -fno-tree-slp-vectorize -DVDOT_BENCH_RANDOM=0
include $(AM_HOME)/Makefile.app
