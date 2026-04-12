#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <cuda_runtime.h>
#include <curand_kernel.h>

#define THREADS_PER_BLOCK 256
#define EPSILON 1e-7f

struct Vec3 {
    float x, y, z;
};

__device__ Vec3 make_vec3(float x, float y, float z) {
    Vec3 v; v.x = x; v.y = y; v.z = z;
    return v;
}

__device__ Vec3 vec3_sub(Vec3 a, Vec3 b) {
    return make_vec3(a.x - b.x, a.y - b.y, a.z - b.z);
}

__device__ float vec3_dot(Vec3 a, Vec3 b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

__device__ Vec3 vec3_cross(Vec3 a, Vec3 b) {
    return make_vec3(
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x
    );
}

// Moller-Trumbore ray-triangle intersection
// Returns hit distance or -1.0f if no hit
__device__ float intersect_triangle(Vec3 origin, Vec3 dir,
                                     Vec3 v0, Vec3 v1, Vec3 v2) {
    Vec3 e1 = vec3_sub(v1, v0);
    Vec3 e2 = vec3_sub(v2, v0);
    Vec3 h = vec3_cross(dir, e2);
    float a = vec3_dot(e1, h);

    if (fabsf(a) < EPSILON) return -1.0f;

    float f = 1.0f / a;
    Vec3 s = vec3_sub(origin, v0);
    float u = f * vec3_dot(s, h);

    if (u < 0.0f || u > 1.0f) return -1.0f;

    Vec3 q = vec3_cross(s, e1);
    float v = f * vec3_dot(dir, q);

    if (v < 0.0f || u + v > 1.0f) return -1.0f;

    float t = f * vec3_dot(e2, q);

    if (t > EPSILON) return t;
    return -1.0f;
}

__global__ void ray_trace_kernel(
    const float* __restrict__ vertexes,   // n_verts * 3 floats
    const int*   __restrict__ triangles,  // n_tris * 3 ints
    int n_tris,
    int n_rays,
    float minx, float miny, float minz,
    float maxx, float maxy, float maxz,
    float* __restrict__ hit_distances     // n_rays floats
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= n_rays) return;

    // Initialize curand
    curandState state;
    curand_init(42, idx, 0, &state);

    // Random origin uniform in AABB
    float ox = minx + curand_uniform(&state) * (maxx - minx);
    float oy = miny + curand_uniform(&state) * (maxy - miny);
    float oz = minz + curand_uniform(&state) * (maxz - minz);
    Vec3 origin = make_vec3(ox, oy, oz);

    // Random direction uniform on sphere
    float theta = acosf(1.0f - 2.0f * curand_uniform(&state));
    float phi = 2.0f * M_PI * curand_uniform(&state);
    float sin_theta = sinf(theta);
    Vec3 dir = make_vec3(sin_theta * cosf(phi), sin_theta * sinf(phi), cosf(theta));

    // Brute-force test against all triangles
    float nearest = -1.0f;
    for (int i = 0; i < n_tris; i++) {
        int i0 = triangles[i * 3 + 0];
        int i1 = triangles[i * 3 + 1];
        int i2 = triangles[i * 3 + 2];

        Vec3 v0 = make_vec3(vertexes[i0 * 3], vertexes[i0 * 3 + 1], vertexes[i0 * 3 + 2]);
        Vec3 v1 = make_vec3(vertexes[i1 * 3], vertexes[i1 * 3 + 1], vertexes[i1 * 3 + 2]);
        Vec3 v2 = make_vec3(vertexes[i2 * 3], vertexes[i2 * 3 + 1], vertexes[i2 * 3 + 2]);

        float t = intersect_triangle(origin, dir, v0, v1, v2);
        if (t > 0.0f) {
            if (nearest < 0.0f || t < nearest) {
                nearest = t;
            }
        }
    }

    hit_distances[idx] = nearest;
}

int main(int argc, char** argv) {
    if (argc != 10) {
        fprintf(stderr, "Usage: %s <n_verts> <n_tris> <n_rays> <minx> <miny> <minz> <maxx> <maxy> <maxz>\n", argv[0]);
        return 1;
    }

    int n_verts = atoi(argv[1]);
    int n_tris  = atoi(argv[2]);
    int n_rays  = atoi(argv[3]);
    float minx  = atof(argv[4]);
    float miny  = atof(argv[5]);
    float minz  = atof(argv[6]);
    float maxx  = atof(argv[7]);
    float maxy  = atof(argv[8]);
    float maxz  = atof(argv[9]);

    printf("Ray tracer: %d verts, %d tris, %d rays\n", n_verts, n_tris, n_rays);
    printf("AABB: [%.0f, %.0f, %.0f] -> [%.0f, %.0f, %.0f]\n", minx, miny, minz, maxx, maxy, maxz);

    // Load vertexes
    FILE* fv = fopen("data/vertexes.bin", "rb");
    if (!fv) { fprintf(stderr, "Cannot open data/vertexes.bin\n"); return 1; }
    size_t vert_bytes = (size_t)n_verts * 3 * sizeof(float);
    float* h_vertexes = (float*)malloc(vert_bytes);
    if (fread(h_vertexes, 1, vert_bytes, fv) != vert_bytes) {
        fprintf(stderr, "Short read on vertexes\n"); return 1;
    }
    fclose(fv);

    // Load triangles
    FILE* ft = fopen("data/triangles.bin", "rb");
    if (!ft) { fprintf(stderr, "Cannot open data/triangles.bin\n"); return 1; }
    size_t tri_bytes = (size_t)n_tris * 3 * sizeof(int);
    int* h_triangles = (int*)malloc(tri_bytes);
    if (fread(h_triangles, 1, tri_bytes, ft) != tri_bytes) {
        fprintf(stderr, "Short read on triangles\n"); return 1;
    }
    fclose(ft);

    // Allocate host output
    size_t ray_bytes = (size_t)n_rays * sizeof(float);
    float* h_hits = (float*)malloc(ray_bytes);

    // Allocate device memory
    float *d_vertexes, *d_hits;
    int *d_triangles;
    cudaMalloc(&d_vertexes, vert_bytes);
    cudaMalloc(&d_triangles, tri_bytes);
    cudaMalloc(&d_hits, ray_bytes);

    // Copy data to device
    cudaMemcpy(d_vertexes, h_vertexes, vert_bytes, cudaMemcpyHostToDevice);
    cudaMemcpy(d_triangles, h_triangles, tri_bytes, cudaMemcpyHostToDevice);

    // Launch kernel with timing
    int blocks = (n_rays + THREADS_PER_BLOCK - 1) / THREADS_PER_BLOCK;

    cudaEvent_t start, stop;
    cudaEventCreate(&start);
    cudaEventCreate(&stop);

    cudaEventRecord(start);
    ray_trace_kernel<<<blocks, THREADS_PER_BLOCK>>>(
        d_vertexes, d_triangles, n_tris, n_rays,
        minx, miny, minz, maxx, maxy, maxz,
        d_hits
    );
    cudaEventRecord(stop);
    cudaEventSynchronize(stop);

    // Check for kernel errors
    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        fprintf(stderr, "CUDA kernel error: %s\n", cudaGetErrorString(err));
        return 1;
    }

    float elapsed_ms;
    cudaEventElapsedTime(&elapsed_ms, start, stop);

    // Copy results back
    cudaMemcpy(h_hits, d_hits, ray_bytes, cudaMemcpyDeviceToHost);

    // Count hits
    int hit_count = 0;
    for (int i = 0; i < n_rays; i++) {
        if (h_hits[i] > 0.0f) hit_count++;
    }

    float hit_rate = 100.0f * hit_count / n_rays;
    float throughput = n_rays / (elapsed_ms / 1000.0f) / 1e6f;

    printf("Kernel time: %.2f ms\n", elapsed_ms);
    printf("Rays traced: %d\n", n_rays);
    printf("Hits: %d (%.2f%%)\n", hit_count, hit_rate);
    printf("Throughput: %.2f M rays/sec\n", throughput);

    // Save hit distances
    FILE* fo = fopen("data/ray_hits.bin", "wb");
    if (!fo) { fprintf(stderr, "Cannot open data/ray_hits.bin for writing\n"); return 1; }
    fwrite(h_hits, sizeof(float), n_rays, fo);
    fclose(fo);
    printf("Saved %d hit distances to data/ray_hits.bin\n", n_rays);

    // Cleanup
    cudaFree(d_vertexes);
    cudaFree(d_triangles);
    cudaFree(d_hits);
    cudaEventDestroy(start);
    cudaEventDestroy(stop);
    free(h_vertexes);
    free(h_triangles);
    free(h_hits);

    return 0;
}
