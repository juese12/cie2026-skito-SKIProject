NAME = cie2026-stage2-vdot-control
SRCS = main.c control.S trap.S legacy.S
MARCH ?= rv64gcv_zba
CONTROL_SEED ?= 0x56444f54
CONTROL_RANDOM_CASES ?= 256
CFLAGS += -fno-tree-vectorize -fno-tree-slp-vectorize -DCONTROL_SEED=$(CONTROL_SEED) -DCONTROL_RANDOM_CASES=$(CONTROL_RANDOM_CASES)
include $(AM_HOME)/Makefile.app
