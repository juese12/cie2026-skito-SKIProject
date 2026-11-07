#ifndef SKIPROJECT_VDOT_TEST_CONTRACT_H
#define SKIPROJECT_VDOT_TEST_CONTRACT_H

// 共享历史源码默认保持仅 e8 的约定；当前镜像适配器
// 显式设置为 1，不能根据参考库路径名推断指令支持范围。
#ifndef VDOT_TEST_E16
#define VDOT_TEST_E16 0
#endif
#if VDOT_TEST_E16 == 1
#define VDOT_BAD_SEW e32
#define VDOT_BAD_VTYPE 16
#define VDOT_BAD_VL 4
#define VDOT_BAD_SEW_LABEL "e32"
#elif VDOT_TEST_E16 == 0
#define VDOT_BAD_SEW e16
#define VDOT_BAD_VTYPE 8
#define VDOT_BAD_VL 8
#define VDOT_BAD_SEW_LABEL "e16"
#else
#error VDOT_TEST_E16 must be 0 (historical e8) or 1 (e8/e16)
#endif
#endif
