#include "gemv.h"
int gemv_oracle(int32_t *y,const int8_t *w,const int8_t *x,size_t m,size_t k) {
  if(m>GEMV_MAX_M || k>GEMV_MAX_K)return 0;
  for(size_t r=0;r<m;++r) {
    int64_t sum=0;
    for(size_t c=0;c<k;++c)sum+=(int64_t)w[r*k+c]*(int64_t)x[c];
    if(sum<INT32_MIN || sum>INT32_MAX)return 0;
    y[r]=(int32_t)sum;
  }
  return 1;
}
