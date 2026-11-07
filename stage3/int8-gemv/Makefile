NAME = cie2026-int8-gemv
SRCS = params.S main.c oracle.c gemv_scalar.c pack.c gemv_rvv.S gemv_vdot.S measure.S
MARCH ?= rv64gcv_zba
CFLAGS += -fno-tree-vectorize -fno-tree-slp-vectorize
include $(AM_HOME)/Makefile.app
