/*
 * clipnode_walk.cu — CUDA BSP v29 clipnode tree walker
 *
 * Walks the BSP hull1 clipnode tree in parallel for 1M+ point-containment
 * queries. Each CUDA thread processes one point independently.
 *
 * Usage: ./clipnode_walk <hull1_start> <n_planes> <n_clipnodes> <n_points>
 *
 * Input files (in data/ directory):
 *   planes.bin     — float32[n_planes * 5]: nx, ny, nz, dist, type_as_float
 *   clipnodes.bin  — int32[n_clipnodes * 4]: planenum, child0, child1, pad
 *   test_points.bin — float32[n_points * 3]: x, y, z
 *
 * Output:
 *   data/gpu_results.bin — int32[n_points]: leaf contents per point
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <cuda_runtime.h>

#define CUDA_CHECK(call) do { \
    cudaError_t err = (call); \
    if (err != cudaSuccess) { \
        fprintf(stderr, "CUDA error at %s:%d: %s\n", \
                __FILE__, __LINE__, cudaGetErrorString(err)); \
        exit(1); \
    } \
} while(0)

/* Kernel: walk clipnode tree for each point */
__global__ void clipnode_walk_kernel(
    const float *planes,      /* n_planes * 5 floats */
    const int   *clipnodes,   /* n_clipnodes * 4 ints */
    const float *points,      /* n_points * 3 floats */
    int         *results,     /* n_points ints */
    int          hull_start,
    int          n_points)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= n_points) return;

    float px = points[idx * 3 + 0];
    float py = points[idx * 3 + 1];
    float pz = points[idx * 3 + 2];

    int node_idx = hull_start;

    while (node_idx >= 0) {
        int planenum = clipnodes[node_idx * 4 + 0];
        int child0   = clipnodes[node_idx * 4 + 1];
        int child1   = clipnodes[node_idx * 4 + 2];

        float nx   = planes[planenum * 5 + 0];
        float ny   = planes[planenum * 5 + 1];
        float nz   = planes[planenum * 5 + 2];
        float dist = planes[planenum * 5 + 3];
        int   type = (int)planes[planenum * 5 + 4];

        float d;
        if (type == 0) {
            d = px - dist;
        } else if (type == 1) {
            d = py - dist;
        } else if (type == 2) {
            d = pz - dist;
        } else {
            d = nx * px + ny * py + nz * pz - dist;
        }

        node_idx = (d >= 0.0f) ? child0 : child1;
    }

    /* node_idx < 0 IS the contents value */
    results[idx] = node_idx;
}

/* Load a binary file into a malloc'd buffer, return byte count */
static size_t load_file(const char *path, void **buf)
{
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "Cannot open %s\n", path);
        exit(1);
    }
    fseek(f, 0, SEEK_END);
    size_t sz = (size_t)ftell(f);
    fseek(f, 0, SEEK_SET);
    *buf = malloc(sz);
    if (!*buf) { fprintf(stderr, "malloc failed\n"); exit(1); }
    size_t rd = fread(*buf, 1, sz, f);
    if (rd != sz) {
        fprintf(stderr, "Short read on %s: got %zu of %zu\n", path, rd, sz);
        exit(1);
    }
    fclose(f);
    return sz;
}

int main(int argc, char **argv)
{
    if (argc != 5) {
        fprintf(stderr, "Usage: %s <hull1_start> <n_planes> <n_clipnodes> <n_points>\n", argv[0]);
        return 1;
    }

    int hull_start  = atoi(argv[1]);
    int n_planes    = atoi(argv[2]);
    int n_clipnodes = atoi(argv[3]);
    int n_points    = atoi(argv[4]);

    printf("Config: hull_start=%d  n_planes=%d  n_clipnodes=%d  n_points=%d\n",
           hull_start, n_planes, n_clipnodes, n_points);

    /* Load input data */
    void *h_planes_raw, *h_clipnodes_raw, *h_points_raw;

    size_t planes_bytes = load_file("data/planes.bin", &h_planes_raw);
    size_t expected_planes = (size_t)n_planes * 5 * sizeof(float);
    if (planes_bytes != expected_planes) {
        fprintf(stderr, "planes.bin size mismatch: got %zu, expected %zu\n",
                planes_bytes, expected_planes);
        return 1;
    }

    size_t clipnodes_bytes = load_file("data/clipnodes.bin", &h_clipnodes_raw);
    size_t expected_clipnodes = (size_t)n_clipnodes * 4 * sizeof(int);
    if (clipnodes_bytes != expected_clipnodes) {
        fprintf(stderr, "clipnodes.bin size mismatch: got %zu, expected %zu\n",
                clipnodes_bytes, expected_clipnodes);
        return 1;
    }

    size_t points_bytes = load_file("data/test_points.bin", &h_points_raw);
    size_t expected_points = (size_t)n_points * 3 * sizeof(float);
    if (points_bytes != expected_points) {
        fprintf(stderr, "test_points.bin size mismatch: got %zu, expected %zu\n",
                points_bytes, expected_points);
        return 1;
    }

    float *h_planes    = (float *)h_planes_raw;
    int   *h_clipnodes = (int *)h_clipnodes_raw;
    float *h_points    = (float *)h_points_raw;

    size_t results_bytes = (size_t)n_points * sizeof(int);
    int *h_results = (int *)malloc(results_bytes);
    if (!h_results) { fprintf(stderr, "malloc failed\n"); return 1; }

    /* Print GPU info */
    cudaDeviceProp prop;
    CUDA_CHECK(cudaGetDeviceProperties(&prop, 0));
    printf("GPU: %s  (SMs: %d, clock: %d MHz)\n",
           prop.name, prop.multiProcessorCount, prop.clockRate / 1000);

    /* Allocate device memory */
    float *d_planes, *d_points;
    int   *d_clipnodes, *d_results;

    CUDA_CHECK(cudaMalloc(&d_planes,    planes_bytes));
    CUDA_CHECK(cudaMalloc(&d_clipnodes, clipnodes_bytes));
    CUDA_CHECK(cudaMalloc(&d_points,    points_bytes));
    CUDA_CHECK(cudaMalloc(&d_results,   results_bytes));

    /* Copy data to GPU */
    CUDA_CHECK(cudaMemcpy(d_planes,    h_planes,    planes_bytes,    cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_clipnodes, h_clipnodes, clipnodes_bytes, cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_points,    h_points,    points_bytes,    cudaMemcpyHostToDevice));

    /* Kernel launch config */
    int threads_per_block = 256;
    int blocks = (n_points + threads_per_block - 1) / threads_per_block;
    printf("Launch: %d blocks x %d threads\n", blocks, threads_per_block);

    /* Warmup pass */
    printf("Running warmup pass...\n");
    clipnode_walk_kernel<<<blocks, threads_per_block>>>(
        d_planes, d_clipnodes, d_points, d_results, hull_start, n_points);
    CUDA_CHECK(cudaDeviceSynchronize());

    /* Timed passes */
    int n_passes = 100;
    cudaEvent_t start, stop;
    CUDA_CHECK(cudaEventCreate(&start));
    CUDA_CHECK(cudaEventCreate(&stop));

    printf("Running %d timed passes...\n", n_passes);
    CUDA_CHECK(cudaEventRecord(start));

    for (int i = 0; i < n_passes; i++) {
        clipnode_walk_kernel<<<blocks, threads_per_block>>>(
            d_planes, d_clipnodes, d_points, d_results, hull_start, n_points);
    }

    CUDA_CHECK(cudaEventRecord(stop));
    CUDA_CHECK(cudaEventSynchronize(stop));

    float ms = 0.0f;
    CUDA_CHECK(cudaEventElapsedTime(&ms, start, stop));

    double total_queries = (double)n_passes * (double)n_points;
    double seconds = ms / 1000.0;
    double mqs = total_queries / seconds / 1e6;

    printf("\nResults:\n");
    printf("  Total time for %d passes: %.3f ms\n", n_passes, ms);
    printf("  Per-pass time: %.3f ms\n", ms / n_passes);
    printf("  Throughput: %.1f M queries/sec\n", mqs);

    /* Copy results back */
    CUDA_CHECK(cudaMemcpy(h_results, d_results, results_bytes, cudaMemcpyDeviceToHost));

    /* Save results */
    FILE *fout = fopen("data/gpu_results.bin", "wb");
    if (!fout) {
        fprintf(stderr, "Cannot open data/gpu_results.bin for writing\n");
        return 1;
    }
    fwrite(h_results, sizeof(int), n_points, fout);
    fclose(fout);
    printf("  Saved %d results to data/gpu_results.bin\n", n_points);

    /* Cleanup */
    CUDA_CHECK(cudaEventDestroy(start));
    CUDA_CHECK(cudaEventDestroy(stop));
    CUDA_CHECK(cudaFree(d_planes));
    CUDA_CHECK(cudaFree(d_clipnodes));
    CUDA_CHECK(cudaFree(d_points));
    CUDA_CHECK(cudaFree(d_results));
    free(h_planes_raw);
    free(h_clipnodes_raw);
    free(h_points_raw);
    free(h_results);

    return 0;
}
