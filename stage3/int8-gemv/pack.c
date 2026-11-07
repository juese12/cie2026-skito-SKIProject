#include "gemv.h"
static int8_t packed_w[GEMV_MAX_M*GEMV_MAX_K] __attribute__((aligned(64)));
static int8_t packed_x[GEMV_MAX_K] __attribute__((aligned(64)));
size_t gemv_pack(int8_t *pw,int8_t *px,const int8_t *w,const int8_t *x,size_t m,size_t k) {
  size_t kp=(k+7u)&~(size_t)7;
  for(size_t c=0;c<kp;++c)px[c]=c<k?x[c]:0;
  for(size_t r=0;r<m;++r)
    for(size_t c=0;c<kp;++c)pw[r*kp+c]=c<k?w[r*k+c]:0;
  return kp;
}
void gemv_dot1_e2e(int32_t *y,const int8_t *w,const int8_t *x,size_t m,size_t k) {
  if(!m)return;
  size_t kp=gemv_pack(packed_w,packed_x,w,x,m,k);
  gemv_dot1(y,packed_w,packed_x,m,kp);
}
void gemv_dot4_e2e(int32_t *y,const int8_t *w,const int8_t *x,size_t m,size_t k) {
  if(!m)return;
  size_t kp=gemv_pack(packed_w,packed_x,w,x,m,k);
  gemv_dot4(y,packed_w,packed_x,m,kp);
}
