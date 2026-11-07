// 在 e16 配置下复用已有分支与异常序列；本程序只调用
// control_branch 和 control_exception，其他引入的辅助代码不使用。
#define VDOT_TEST_E16 1
#define e8 e16
#include "../control-tests/control.S"
