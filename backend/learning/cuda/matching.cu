// Bounded exact rectangular assignment for baseline-v1 (at most 16 queries).
// Primal-dual Hungarian algorithm; double potentials over FP32 input costs.
// Each frame is independent. No host readback, allocation, or synchronization.
#include <cuda_runtime.h>
#include <cstdint>
#include <cmath>
#include <cfloat>

__global__ void assign(const float* costs, const int64_t* counts,
                       int64_t* result, int queries, int capacity) {
    // Grid has exactly one block per frame, one active thread per block.
    if (threadIdx.x != 0) return;
    const int f = blockIdx.x;
    const int n = static_cast<int>(counts[f]);
    for (int q = 0; q < queries; ++q) result[f * queries + q] = -1;
    if (n < 0 || n > capacity) {
        for (int q = 0; q < queries; ++q) result[f * queries + q] = -2;
        return;
    }
    for (int q = 0; q < queries; ++q) for (int t = 0; t < n; ++t) {
        if (!isfinite(costs[(f * queries + q) * capacity + t])) {
            for (int j = 0; j < queries; ++j) result[f * queries + j] = -2;
            return;
        }
    }
    double u[17] = {}, v[17] = {};
    int owner[17] = {}, previous[17] = {};
    for (int t = 1; t <= n; ++t) {
        owner[0] = t;
        int column = 0;
        double distance[17];
        bool visited[17] = {};
        for (int q = 1; q <= queries; ++q) distance[q] = DBL_MAX;
        do {
            visited[column] = true;
            const int target = owner[column];
            double delta = DBL_MAX;
            int next = 0;
            for (int q = 1; q <= queries; ++q) {
                if (visited[q]) continue;
                const double reduced = static_cast<double>(costs[(f * queries + q - 1) * capacity + target - 1])
                    - u[target] - v[q];
                if (reduced < distance[q]) {
                    distance[q] = reduced;
                    previous[q] = column;
                }
                if (distance[q] < delta || (distance[q] == delta && owner[q] == 0 && owner[next] != 0)) {
                    delta = distance[q]; next = q;
                }
            }
            for (int q = 0; q <= queries; ++q) {
                if (visited[q]) { u[owner[q]] += delta; v[q] -= delta; }
                else if (q) distance[q] -= delta;
            }
            column = next;
        } while (owner[column] != 0);
        do {
            const int next = previous[column];
            owner[column] = owner[next];
            column = next;
        } while (column);
    }
    for (int q = 1; q <= queries; ++q)
        if (owner[q]) result[f * queries + q - 1] = owner[q] - 1;
}

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif
extern "C" EXPORT int learning_assign(const float* costs, const int64_t* counts,
    int64_t* result, int batch, int queries, int capacity, void* stream) {
    if (queries < 1 || queries > 16 || capacity < 1 || capacity > queries || batch < 1) return -1;
    assign<<<batch, 1, 0, static_cast<cudaStream_t>(stream)>>>(costs, counts, result, queries, capacity);
    return static_cast<int>(cudaGetLastError());
}

struct Point { float x, z; };
__device__ float side(Point a, Point b, Point p) {
    const float dx = b.x-a.x, dz = b.z-a.z;
    return dx*(p.z-a.z)-dz*(p.x-a.x);
}
__global__ void overlaps(const float* a, const float* b, const int64_t* na,
    const int64_t* nb, float* output, int batch, int np, int nt) {
    int index = blockIdx.x*blockDim.x+threadIdx.x;
    if (index >= batch*np*nt) return;
    const int f = index/(np*nt), p = (index/nt)%np, t = index%nt;
    output[index] = 0;
    if (p >= na[f] || t >= nb[f]) return;
    // CPU-prepared rectangle corners, vertical endpoints and volumes retain
    // NumPy's FP32 rounding. All clipping operations use the reference order.
    const float* left = a+(f*np+p)*11;
    const float* right = b+(f*nt+t)*11;
    const float height = fmaxf(0, fminf(left[9],right[9])-fmaxf(left[8],right[8]));
    if (height == 0) return;
    Point polygon[16], temporary[16];
    int count = 4;
    for (int j=0;j<4;++j) polygon[j]={left[2*j],left[2*j+1]};
    for (int edge=0;edge<4 && count;++edge) {
        Point start={right[2*edge],right[2*edge+1]};
        const int next=(edge+1)%4;
        Point end={right[2*next],right[2*next+1]};
        int length=0;
        Point previous=polygon[count-1];
        float previous_side=side(start,end,previous);
        for (int j=0;j<count;++j) {
            Point current=polygon[j];
            float current_side=side(start,end,current);
            if ((current_side >= -1e-10f) != (previous_side >= -1e-10f)) {
                float fraction=previous_side/(previous_side-current_side);
                temporary[length++]={previous.x+fraction*(current.x-previous.x),
                                     previous.z+fraction*(current.z-previous.z)};
            }
            if (current_side >= -1e-10f) temporary[length++]=current;
            previous=current; previous_side=current_side;
        }
        count=length;
        for (int j=0;j<count;++j) polygon[j]=temporary[j];
    }
    float area=0;
    if (count>=3) {
        for (int j=0;j<count;++j) {
            const Point p=polygon[j], q=polygon[(j+1)%count];
            area += p.x*q.z-p.z*q.x;
        }
        area=fabsf(area)/2;
    }
    const float intersection=area*height;
    output[index]=fminf(1,fmaxf(0,intersection/(left[10]+right[10]-intersection)));
}
extern "C" EXPORT int learning_overlaps(const float* left, const float* right,
    const int64_t* na, const int64_t* nb, float* output, int batch, int np, int nt, void* stream) {
    if (batch<1 || np<1 || np>16 || nt<1 || nt>16) return -1;
    overlaps<<<(batch*np*nt+127)/128,128,0,static_cast<cudaStream_t>(stream)>>>(left,right,na,nb,output,batch,np,nt);
    return static_cast<int>(cudaGetLastError());
}
