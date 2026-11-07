KIND ?= functional
RANDOM_CASES ?= 0
CONTROL_SEED ?= 0x56444f54
ARCH ?= riscv64-xs
.DEFAULT_GOAL := default
ifeq ($(KIND),functional)
NAME = cie2026-contract-functional-r$(RANDOM_CASES)
SRCS = functional-main.c functional.S functional-trap.S
else ifeq ($(KIND),control)
NAME = cie2026-contract-control-seed$(CONTROL_SEED)
SRCS = control-main.c control.S control-trap.S control-legacy.S
else
$(error KIND must be functional or control)
endif
MARCH ?= rv64gcv_zba
DST_DIR = $(CURDIR)/build/contract-v2-$(KIND)-r$(RANDOM_CASES)-seed$(CONTROL_SEED)/
BINARY = $(DST_DIR)$(NAME)-$(ARCH)
CFLAGS += -fno-tree-vectorize -fno-tree-slp-vectorize -DVDOT_RANDOM_CASES=$(RANDOM_CASES) -DCONTROL_SEED=$(CONTROL_SEED)
# 路径查询不加载 AM 的编译规则，也不创建目录或调用工具链。
.PHONY: print-image
print-image:
	@printf '%s\n' '$(BINARY).bin'
ifneq ($(MAKECMDGOALS),print-image)
include $(AM_HOME)/Makefile.app
endif
