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
