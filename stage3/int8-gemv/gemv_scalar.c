#include "gemv.h"
void gemv_scalar(int32_t *y,const int8_t *w,const int8_t *x,size_t m,size_t k) {
  for(size_t r=0;r<m;++r) {
    int32_t sum=0;
    for(size_t c=0;c<k;++c)sum+=(int32_t)w[r*k+c]*(int32_t)x[c];
    y[r]=sum;
  }
}
