NAME = cie2026-stage2-vdot
SRCS = main.c vdot.S trap.S
MARCH ?= rv64gcv_zba
VDOT_RANDOM_CASES ?= 1000
VDOT_ORDINARY_ONLY ?= 0
CFLAGS += -fno-tree-vectorize -fno-tree-slp-vectorize -DVDOT_RANDOM_CASES=$(VDOT_RANDOM_CASES) -DVDOT_ORDINARY_ONLY=$(VDOT_ORDINARY_ONLY)
include $(AM_HOME)/Makefile.app
