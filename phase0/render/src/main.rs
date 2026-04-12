use std::fs;
use std::path::Path;

fn main() {
    let data_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../data");

    // ── Load vertexes ──────────────────────────────────────────────────────
    let vert_bytes = fs::read(data_dir.join("vertexes.bin"))
        .expect("failed to read vertexes.bin");
    let vertexes: &[f32] = bytemuck::cast_slice(&vert_bytes);
    let n_verts = vertexes.len() / 3;
    println!("Vertexes: {n_verts}");

    // ── Load triangles ─────────────────────────────────────────────────────
    let tri_bytes = fs::read(data_dir.join("triangles.bin"))
        .expect("failed to read triangles.bin");
    let triangles: &[i32] = bytemuck::cast_slice(&tri_bytes);
    let n_tris = triangles.len() / 3;
    println!("Triangles: {n_tris}");

    // ── Compute 2D AABB (X, Y) ────────────────────────────────────────────
    let mut min_x = f32::INFINITY;
    let mut max_x = f32::NEG_INFINITY;
    let mut min_y = f32::INFINITY;
    let mut max_y = f32::NEG_INFINITY;
    let mut min_z = f32::INFINITY;
    let mut max_z = f32::NEG_INFINITY;

    for i in 0..n_verts {
        let x = vertexes[i * 3];
        let y = vertexes[i * 3 + 1];
        let z = vertexes[i * 3 + 2];
        min_x = min_x.min(x);
        max_x = max_x.max(x);
        min_y = min_y.min(y);
        max_y = max_y.max(y);
        min_z = min_z.min(z);
        max_z = max_z.max(z);
    }

    println!("AABB X: [{min_x}, {max_x}]");
    println!("AABB Y: [{min_y}, {max_y}]");
    println!("AABB Z: [{min_z}, {max_z}]");

    // ── Image setup ────────────────────────────────────────────────────────
    let img_w: u32 = 1024;
    let img_h: u32 = 1024;
    let margin = 16.0_f32;

    // Compute scale to fit both axes with margin, preserving aspect ratio
    let world_w = max_x - min_x;
    let world_h = max_y - min_y;
    let usable = (img_w as f32) - 2.0 * margin;
    let scale = usable / world_w.max(world_h);

    // Center offsets
    let off_x = margin + (usable - world_w * scale) * 0.5;
    let off_y = margin + (usable - world_h * scale) * 0.5;

    // Project world X,Y → pixel
    let to_px = |wx: f32, wy: f32| -> (f32, f32) {
        let px = (wx - min_x) * scale + off_x;
        // Flip Y so +Y in Quake world is up in the image
        let py = (img_h as f32) - ((wy - min_y) * scale + off_y);
        (px, py)
    };

    // Z range for depth shading
    let z_range = max_z - min_z;

    // Pixel buffers: RGBA + depth (f32, init to +INF = no geometry)
    let n_pixels = (img_w * img_h) as usize;
    let mut depth_buf = vec![f32::INFINITY; n_pixels];
    let mut color_buf = vec![0u8; n_pixels * 4]; // RGBA

    // ── Rasterize ──────────────────────────────────────────────────────────
    for t in 0..n_tris {
        let i0 = triangles[t * 3] as usize;
        let i1 = triangles[t * 3 + 1] as usize;
        let i2 = triangles[t * 3 + 2] as usize;

        // Bounds check
        if i0 >= n_verts || i1 >= n_verts || i2 >= n_verts {
            continue;
        }

        // World coords
        let (x0, y0, z0) = (vertexes[i0 * 3], vertexes[i0 * 3 + 1], vertexes[i0 * 3 + 2]);
        let (x1, y1, z1) = (vertexes[i1 * 3], vertexes[i1 * 3 + 1], vertexes[i1 * 3 + 2]);
        let (x2, y2, z2) = (vertexes[i2 * 3], vertexes[i2 * 3 + 1], vertexes[i2 * 3 + 2]);

        // Project to pixel space
        let (px0, py0) = to_px(x0, y0);
        let (px1, py1) = to_px(x1, y1);
        let (px2, py2) = to_px(x2, y2);

        // Bounding box in pixel space
        let bb_min_x = px0.min(px1).min(px2).floor() as i32;
        let bb_max_x = px0.max(px1).max(px2).ceil() as i32;
        let bb_min_y = py0.min(py1).min(py2).floor() as i32;
        let bb_max_y = py0.max(py1).max(py2).ceil() as i32;

        // Clip to image
        let bb_min_x = bb_min_x.max(0) as u32;
        let bb_max_x = (bb_max_x as u32).min(img_w - 1);
        let bb_min_y = bb_min_y.max(0) as u32;
        let bb_max_y = (bb_max_y as u32).min(img_h - 1);

        // Edge function denominator (2x signed area)
        let denom = (px1 - px0) * (py2 - py0) - (px2 - px0) * (py1 - py0);
        if denom.abs() < 1e-6 {
            continue; // Degenerate triangle
        }
        let inv_denom = 1.0 / denom;

        for py in bb_min_y..=bb_max_y {
            for px in bb_min_x..=bb_max_x {
                let fpx = px as f32 + 0.5;
                let fpy = py as f32 + 0.5;

                // Barycentric coordinates
                let w1 = ((fpx - px0) * (py2 - py0) - (px2 - px0) * (fpy - py0)) * inv_denom;
                let w2 = ((px1 - px0) * (fpy - py0) - (fpx - px0) * (py1 - py0)) * inv_denom;
                let w0 = 1.0 - w1 - w2;

                if w0 >= 0.0 && w1 >= 0.0 && w2 >= 0.0 {
                    // Interpolate Z
                    let z = w0 * z0 + w1 * z1 + w2 * z2;

                    let idx = (py * img_w + px) as usize;

                    // Minimum-Z depth test (closest to top-down viewer = lowest Z wins)
                    if z < depth_buf[idx] {
                        depth_buf[idx] = z;

                        // Depth shade: lower Z = darker (floors), higher Z = lighter (ceilings)
                        let t_val = ((z - min_z) / z_range).clamp(0.0, 1.0);
                        let gray = (t_val * 230.0 + 20.0) as u8; // 20..250 range

                        color_buf[idx * 4] = gray;
                        color_buf[idx * 4 + 1] = gray;
                        color_buf[idx * 4 + 2] = gray;
                        color_buf[idx * 4 + 3] = 255;
                    }
                }
            }
        }
    }

    // ── Save image ─────────────────────────────────────────────────────────
    let out_path = data_dir.join("dm3_topdown.png");
    let img = image::RgbaImage::from_raw(img_w, img_h, color_buf)
        .expect("failed to create image from buffer");
    img.save(&out_path).expect("failed to save PNG");

    println!("Image: {}x{}", img_w, img_h);
    println!("Saved: {}", out_path.display());
}
