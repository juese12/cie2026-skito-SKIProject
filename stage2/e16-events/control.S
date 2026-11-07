// 在明确配置 e16 后复用已验证的分支与异常指令序列。
// 本短程序只调用 control_branch 和 control_exception。
#define VDOT_TEST_E16 1
#define e8 e16
#include "../control-tests/control.S"
