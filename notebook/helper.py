from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image, ImageChops, ImageDraw, ImageFont
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from rasterio.warp import Resampling

_TERRAIN_STOPS = (
    (0.0, (35, 100, 55)),
    (0.2, (115, 160, 85)),
    (0.4, (205, 195, 125)),
    (0.62, (160, 125, 90)),
    (0.82, (185, 180, 170)),
    (1.0, (255, 255, 255)),
)
_BACKGROUND = (233, 238, 242)
_BOUNDARY_COLOR = (37, 37, 37)
_OUTLET_COLOR = (215, 48, 39)


def _font(size):
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _terrain_rgb(values, mask, low, high):
    normalized = np.clip((values.astype("float32") - low) / (high - low), 0, 1)
    stops = np.array([position for position, _ in _TERRAIN_STOPS])
    colors = np.array([color for _, color in _TERRAIN_STOPS])
    rgb = np.stack(
        [np.interp(normalized, stops, colors[:, channel]) for channel in range(3)],
        axis=-1,
    ).astype("uint8")
    rgb[mask] = _BACKGROUND
    return rgb


def _nice_tick_step(span, target_intervals=4):
    raw_step = span / target_intervals
    magnitude = 10 ** np.floor(np.log10(raw_step))
    normalized_step = raw_step / magnitude
    factor = next(value for value in (1, 2, 5, 10) if value >= normalized_step)
    return factor * magnitude


def plot_dem(
    dem_path,
    output_path,
    title,
    outlet_path,
    watershed_boundary=None,
    preview_max_size=1600,
):
    dem_path = Path(dem_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(dem_path) as src:
        scale = min(1.0, preview_max_size / max(src.width, src.height))
        height = max(1, round(src.height * scale))
        width = max(1, round(src.width * scale))
        dem_preview = src.read(
            1,
            out_shape=(height, width),
            resampling=Resampling.average,
        )
        preview_mask = src.read_masks(
            1,
            out_shape=(height, width),
            resampling=Resampling.nearest,
        ) == 0
        bounds = src.bounds
        dem_crs = src.crs

    if preview_mask.all():
        raise ValueError(f"The DEM contains no valid pixels to plot: {dem_path}")

    valid_rows, valid_cols = np.nonzero(~preview_mask)
    padding = max(2, round(max(height, width) * 0.015))
    row_start = max(0, int(valid_rows.min()) - padding)
    row_stop = min(height, int(valid_rows.max()) + padding + 1)
    col_start = max(0, int(valid_cols.min()) - padding)
    col_stop = min(width, int(valid_cols.max()) + padding + 1)
    preview = dem_preview[row_start:row_stop, col_start:col_stop]
    preview_mask = preview_mask[row_start:row_stop, col_start:col_stop]
    pixel_width = (bounds.right - bounds.left) / width
    pixel_height = (bounds.top - bounds.bottom) / height
    bounds = rasterio.coords.BoundingBox(
        left=bounds.left + col_start * pixel_width,
        bottom=bounds.top - row_stop * pixel_height,
        right=bounds.left + col_stop * pixel_width,
        top=bounds.top - row_start * pixel_height,
    )
    height, width = preview.shape

    valid_values = preview[~preview_mask]
    low, high = np.percentile(valid_values, [2, 98])
    if low == high:
        low, high = float(valid_values.min()), float(valid_values.max()) + 1
    preview = _terrain_rgb(dem_preview, preview_mask, low, high)

    if watershed_boundary is not None:
        boundary_geometries = [
            geometry.boundary
            for geometry in watershed_boundary.to_crs(dem_crs).geometry
            if not geometry.is_empty
        ]
        if boundary_geometries:
            boundary_mask = rasterize(
                [(geometry, 1) for geometry in boundary_geometries],
                out_shape=(height, width),
                transform=from_bounds(
                    bounds.left,
                    bounds.bottom,
                    bounds.right,
                    bounds.top,
                    width,
                    height,
                ),
                fill=0,
                all_touched=True,
                dtype="uint8",
            )
            preview[boundary_mask > 0] = _BOUNDARY_COLOR

    outlet_gdf = gpd.read_file(outlet_path).to_crs(dem_crs)
    outlet = outlet_gdf.geometry.iloc[0]
    if outlet.geom_type != "Point":
        raise ValueError(f"The snapped outlet must be a point, not {outlet.geom_type}.")

    map_width = bounds.right - bounds.left
    map_height = bounds.top - bounds.bottom
    tick_step = _nice_tick_step(max(map_width, map_height), target_intervals=6)
    padding = 0.01
    view_left = bounds.left - map_width * padding
    view_right = bounds.right + map_width * padding
    view_bottom = bounds.bottom - map_height * padding
    view_top = bounds.top + map_height * padding
    view_width = view_right - view_left
    view_height = view_top - view_bottom
    pixels_per_unit = min(790 / view_width, 790 / view_height)
    frame_width = round((view_right - view_left) * pixels_per_unit)
    frame_height = round((view_top - view_bottom) * pixels_per_unit)
    map_left, map_top = 130, 82
    map_right = map_left + frame_width
    map_bottom = map_top + frame_height
    colorbar_x = map_right + 20
    colorbar_top, colorbar_bottom = map_top + 6, map_bottom - 6
    canvas = Image.new("RGB", (colorbar_x + 24 + 100, map_bottom + 105), "white")
    draw = ImageDraw.Draw(canvas)
    title_font = _font(28)
    label_font = _font(17)
    small_font = _font(14)
    draw.text((canvas.width // 2, 34), title, fill=(32, 32, 32), font=title_font, anchor="mm")

    image_width = max(1, round(map_width * pixels_per_unit))
    image_height = max(1, round(map_height * pixels_per_unit))
    preview_image = Image.fromarray(preview).resize(
        (image_width, image_height),
        Image.Resampling.BILINEAR,
    )
    image_x = round(map_left + (bounds.left - view_left) * pixels_per_unit)
    image_y = round(map_top + (view_top - bounds.top) * pixels_per_unit)
    canvas.paste(preview_image, (image_x, image_y))
    draw.rectangle((map_left, map_top, map_right, map_bottom), outline=(65, 65, 65), width=2)

    tick_font = _font(13)
    for easting in np.arange(
        np.ceil(view_left / tick_step) * tick_step,
        view_right,
        tick_step,
    ):
        x = round(map_left + (easting - view_left) * pixels_per_unit)
        draw.line((x, map_bottom, x, map_bottom + 7), fill=(32, 32, 32), width=1)
        draw.text(
            (x, map_bottom + 12),
            f"{easting / 1000:.3f}".rstrip("0").rstrip("."),
            fill=(32, 32, 32),
            font=tick_font,
            anchor="mt",
        )

    for northing in np.arange(
        np.floor(view_top / tick_step) * tick_step,
        view_bottom,
        -tick_step,
    ):
        y = round(map_top + (view_top - northing) * pixels_per_unit)
        draw.line((map_left - 7, y, map_left, y), fill=(32, 32, 32), width=1)
        draw.text(
            (map_left - 12, y),
            f"{northing / 1000:.3f}".rstrip("0").rstrip("."),
            fill=(32, 32, 32),
            font=tick_font,
            anchor="rm",
        )

    outlet_x = round(map_left + (outlet.x - view_left) * pixels_per_unit)
    outlet_y = round(map_top + (view_top - outlet.y) * pixels_per_unit)
    draw.ellipse(
        (outlet_x - 7, outlet_y - 7, outlet_x + 7, outlet_y + 7),
        fill=_OUTLET_COLOR,
        outline="white",
        width=2,
    )

    arrow_x, arrow_y = map_right - 38, map_top + 55
    draw.text((arrow_x, arrow_y - 24), "N", fill=(32, 32, 32), font=label_font, anchor="mm")
    draw.line((arrow_x, arrow_y + 18, arrow_x, arrow_y - 5), fill=(32, 32, 32), width=3)
    draw.polygon(
        ((arrow_x, arrow_y - 12), (arrow_x - 8, arrow_y + 2), (arrow_x + 8, arrow_y + 2)),
        fill=(32, 32, 32),
    )

    scale_target = map_width * 0.18
    scale_power = 10 ** np.floor(np.log10(scale_target))
    scale_length = next(
        factor * scale_power
        for factor in (5, 2, 1)
        if factor * scale_power <= scale_target
    )
    scale_label = f"{scale_length / 1000:g} km" if scale_length >= 1000 else f"{scale_length:g} m"
    scale_x = map_left + 32
    scale_y = map_bottom - 38
    scale_end = round(scale_x + scale_length * pixels_per_unit)
    draw.rectangle((scale_x - 8, scale_y - 24, scale_end + 8, scale_y + 12), fill="white")
    draw.line((scale_x, scale_y, scale_end, scale_y), fill=(32, 32, 32), width=4)
    for x in (scale_x, scale_end):
        draw.line((x, scale_y - 5, x, scale_y + 5), fill=(32, 32, 32), width=2)
    draw.text(((scale_x + scale_end) // 2, scale_y - 8), scale_label, fill=(32, 32, 32), font=small_font, anchor="ms")

    legend_x, legend_y = map_left + 14, map_top + 14
    legend_items = 2 if watershed_boundary is not None else 1
    draw.rectangle(
        (legend_x, legend_y, legend_x + 205, legend_y + 20 + 25 * legend_items),
        fill="white",
        outline=(180, 180, 180),
    )
    if watershed_boundary is not None:
        draw.line((legend_x + 10, legend_y + 14, legend_x + 38, legend_y + 14), fill=_BOUNDARY_COLOR, width=3)
        draw.text((legend_x + 46, legend_y + 14), "Watershed boundary", fill=(32, 32, 32), font=small_font, anchor="lm")
        outlet_legend_y = legend_y + 39
    else:
        outlet_legend_y = legend_y + 14
    draw.ellipse(
        (legend_x + 10, outlet_legend_y - 5, legend_x + 20, outlet_legend_y + 5),
        fill=_OUTLET_COLOR,
        outline="white",
        width=1,
    )
    draw.text((legend_x + 28, outlet_legend_y), "Snapped outlet", fill=(32, 32, 32), font=small_font, anchor="lm")

    draw.text(
        (colorbar_x + 14, colorbar_top - 15),
        "Elevation (m)",
        fill=(32, 32, 32),
        font=small_font,
        anchor="mb",
    )
    gradient = np.linspace(1, 0, colorbar_bottom - colorbar_top, dtype="float32")[:, None]
    gradient_rgb = _terrain_rgb(gradient, np.zeros_like(gradient, dtype=bool), 0, 1)
    gradient_image = Image.fromarray(gradient_rgb).resize((24, colorbar_bottom - colorbar_top))
    canvas.paste(gradient_image, (colorbar_x, colorbar_top))
    draw.rectangle(
        (colorbar_x, colorbar_top, colorbar_x + 24, colorbar_bottom),
        outline=(80, 80, 80),
        width=1,
    )
    for fraction in (0, 0.25, 0.5, 0.75, 1):
        y = round(colorbar_top + fraction * (colorbar_bottom - colorbar_top))
        elevation = high - fraction * (high - low)
        draw.line((colorbar_x + 24, y, colorbar_x + 30, y), fill=(32, 32, 32), width=1)
        draw.text(
            (colorbar_x + 36, y),
            f"{elevation:.0f}",
            fill=(32, 32, 32),
            font=small_font,
            anchor="lm",
        )

    draw.text(
        ((map_left + map_right) // 2, map_bottom + 52),
        "Easting (10^3 m)",
        fill=(32, 32, 32),
        font=label_font,
        anchor="mm",
    )
    northing_text = "Northing (10^3 m)"
    northing_bounds = draw.textbbox((0, 0), northing_text, font=label_font)
    northing_label = Image.new(
        "RGBA",
        (northing_bounds[2] - northing_bounds[0] + 4, northing_bounds[3] - northing_bounds[1] + 4),
        (255, 255, 255, 0),
    )
    ImageDraw.Draw(northing_label).text(
        (2 - northing_bounds[0], 2 - northing_bounds[1]),
        northing_text,
        fill=(32, 32, 32),
        font=label_font,
    )
    northing_label = northing_label.rotate(90, expand=True)
    canvas.paste(
        northing_label,
        (34 - northing_label.width // 2, (map_top + map_bottom - northing_label.height) // 2),
        northing_label,
    )
    content = ImageChops.difference(canvas, Image.new("RGB", canvas.size, "white")).getbbox()
    if content is not None:
        margin = 14
        crop = (
            max(0, content[0] - margin),
            max(0, content[1] - margin),
            min(canvas.width, content[2] + margin),
            min(canvas.height, content[3] + margin),
        )
        canvas = canvas.crop(crop)
    canvas.save(output_path)
    return output_path


def plot_screening_suite(
    dem,
    valid_mask,
    flow_accumulation,
    extent,
    streams,
    stream_widths,
    profile_distance_km,
    profile_elevation_m,
    candidates,
    outlet_xy,
    figures_dir,
):
    figures_dir = Path(figures_dir)
    figures_dir.mkdir(parents=True, exist_ok=True)
    dem = np.asarray(dem.filled(np.nan) if np.ma.isMaskedArray(dem) else dem, dtype="float32")
    valid_mask = np.asarray(valid_mask, dtype=bool)
    flow_accumulation = np.asarray(
        flow_accumulation.filled(0) if np.ma.isMaskedArray(flow_accumulation) else flow_accumulation,
        dtype="float32",
    )
    if dem.shape != valid_mask.shape or dem.shape != flow_accumulation.shape:
        raise ValueError("DEM, watershed mask, and flow-accumulation previews must have matching shapes.")
    if not valid_mask.any():
        raise ValueError("The watershed preview contains no valid cells.")

    x_min, x_max, y_min, y_max = map(float, extent)
    if not x_min < x_max or not y_min < y_max:
        raise ValueError(f"Invalid map extent: {extent}")
    canvas_width, canvas_height = 1400, 1100
    map_area = (145, 95, 1000, 920)
    map_scale = min(
        (map_area[2] - map_area[0]) / (x_max - x_min),
        (map_area[3] - map_area[1]) / (y_max - y_min),
    )
    map_width = max(1, round((x_max - x_min) * map_scale))
    map_height = max(1, round((y_max - y_min) * map_scale))
    map_left = map_area[0] + (map_area[2] - map_area[0] - map_width) // 2
    map_top = map_area[1] + (map_area[3] - map_area[1] - map_height) // 2
    map_right, map_bottom = map_left + map_width, map_top + map_height

    low, high = np.percentile(dem[valid_mask & np.isfinite(dem)], [2, 98])
    if low == high:
        high = low + 1
    dem_rgb = _terrain_rgb(np.nan_to_num(dem, nan=low), ~valid_mask | ~np.isfinite(dem), low, high)
    boundary = valid_mask & ~(
        np.roll(valid_mask, 1, axis=0)
        & np.roll(valid_mask, -1, axis=0)
        & np.roll(valid_mask, 1, axis=1)
        & np.roll(valid_mask, -1, axis=1)
    )
    dem_rgb[boundary] = (215, 48, 39)

    font = _font(17)
    small_font = _font(14)
    tick_font = _font(13)

    def map_point(x, y):
        return (
            round(map_left + (x - x_min) * map_scale),
            round(map_top + (y_max - y) * map_scale),
        )

    def base_canvas(title):
        image = Image.new("RGB", (canvas_width, canvas_height), "white")
        draw = ImageDraw.Draw(image)
        draw.text((canvas_width // 2, 35), title, fill=(32, 32, 32), font=_font(25), anchor="mm")
        draw.rectangle((map_left, map_top, map_right, map_bottom), outline=(65, 65, 65), width=2)
        for fraction in np.linspace(0, 1, 5):
            x = round(map_left + fraction * map_width)
            y = round(map_top + fraction * map_height)
            easting = x_min + fraction * (x_max - x_min)
            northing = y_max - fraction * (y_max - y_min)
            draw.line((x, map_bottom, x, map_bottom + 6), fill=(32, 32, 32), width=1)
            draw.text((x, map_bottom + 10), f"{easting / 1000:.0f}", fill=(32, 32, 32), font=tick_font, anchor="mt")
            draw.line((map_left - 6, y, map_left, y), fill=(32, 32, 32), width=1)
            draw.text((map_left - 10, y), f"{northing / 1000:.0f}", fill=(32, 32, 32), font=tick_font, anchor="rm")
        draw.text(((map_left + map_right) // 2, map_bottom + 45), "Easting (10^3 m)", fill=(32, 32, 32), font=font, anchor="mm")
        north_label = Image.new("RGBA", (150, 25), (255, 255, 255, 0))
        ImageDraw.Draw(north_label).text((2, 2), "Northing (10^3 m)", fill=(32, 32, 32), font=small_font)
        north_label = north_label.rotate(90, expand=True)
        image.paste(north_label, (28, (map_top + map_bottom - north_label.height) // 2), north_label)
        draw.text((map_right - 22, map_top + 26), "N", fill=(32, 32, 32), font=font, anchor="mm")
        draw.line((map_right - 22, map_top + 58, map_right - 22, map_top + 34), fill=(32, 32, 32), width=3)
        draw.polygon(((map_right - 22, map_top + 29), (map_right - 30, map_top + 43), (map_right - 14, map_top + 43)), fill=(32, 32, 32))
        return image, draw

    def paste_raster(image, rgb):
        preview = Image.fromarray(rgb).resize((map_width, map_height), Image.Resampling.BILINEAR)
        image.paste(preview, (map_left, map_top))
        ImageDraw.Draw(image).rectangle((map_left, map_top, map_right, map_bottom), outline=(65, 65, 65), width=2)

    def draw_watershed_outline(draw):
        rows, cols = np.nonzero(boundary)
        points = [
            (
                map_left + round((col + 0.5) * map_width / dem.shape[1]),
                map_top + round((row + 0.5) * map_height / dem.shape[0]),
            )
            for row, col in zip(rows, cols)
        ]
        draw.point(points, fill=(215, 48, 39))

    def draw_outlet(draw, color=(215, 48, 39)):
        x, y = map_point(*outlet_xy)
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=color, outline="white", width=2)

    def add_colorbar(image, values, label, palette):
        draw = ImageDraw.Draw(image)
        x, top, bottom = map_right + 35, map_top + 8, map_bottom - 8
        draw.text((x + 12, top - 12), label, fill=(32, 32, 32), font=small_font, anchor="mb")
        if palette == "elevation":
            gradient = _terrain_rgb(np.linspace(1, 0, bottom - top)[:, None], np.zeros((bottom - top, 1), bool), 0, 1)
        elif palette == "flow":
            positions = np.linspace(0, 1, 256)
            colors = np.array(((247, 251, 255), (107, 174, 214), (8, 81, 156)))
            gradient = np.stack(
                [np.interp(positions, (0, 0.5, 1), colors[:, channel]) for channel in range(3)],
                axis=-1,
            ).astype("uint8")[:, None, :]
            gradient = np.repeat(gradient[::-1], max(1, (bottom - top) // 256), axis=0)[: bottom - top]
            if len(gradient) < bottom - top:
                gradient = np.resize(gradient, (bottom - top, 1, 3))
        else:
            positions = np.linspace(0, 1, bottom - top)
            colors = np.array(((13, 8, 135), (126, 3, 168), (204, 71, 120), (248, 149, 64), (240, 249, 33)))
            gradient = np.stack(
                [np.interp(positions, np.linspace(0, 1, len(colors)), colors[:, channel]) for channel in range(3)],
                axis=-1,
            ).astype("uint8")[:, None, :]
            gradient = gradient[::-1]
        image.paste(Image.fromarray(gradient).resize((22, bottom - top)), (x, top))
        draw.rectangle((x, top, x + 22, bottom), outline=(80, 80, 80), width=1)
        finite = np.asarray(values)
        finite = finite[np.isfinite(finite)]
        if finite.size:
            vmin, vmax = float(finite.min()), float(finite.max())
            for fraction in (0, 0.25, 0.5, 0.75, 1):
                y = round(top + fraction * (bottom - top))
                value = vmax - fraction * (vmax - vmin)
                draw.text((x + 30, y), f"{value:.0f}", fill=(32, 32, 32), font=small_font, anchor="lm")

    def draw_streams(draw, widths, color=(70, 130, 180)):
        for geometry, line_width in zip(streams.geometry, widths):
            if geometry is None or geometry.is_empty:
                continue
            parts = geometry.geoms if geometry.geom_type == "MultiLineString" else (geometry,)
            for part in parts:
                points = [map_point(x, y) for x, y, *_ in part.coords]
                if len(points) > 1:
                    draw.line(points, fill=color, width=max(1, round(float(line_width))), joint="curve")

    def save_map(image, name):
        content = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
        if content:
            margin = 14
            image = image.crop(
                (
                    max(0, content[0] - margin),
                    max(0, content[1] - margin),
                    min(image.width, content[2] + margin),
                    min(image.height, content[3] + margin),
                )
            )
        path = figures_dir / name
        image.save(path)
        return path

    output_paths = []
    image, draw = base_canvas("DEM - Watershed")
    paste_raster(image, dem_rgb)
    draw = ImageDraw.Draw(image)
    draw_outlet(draw)
    add_colorbar(image, dem[valid_mask], "Elevation (m)", "elevation")
    output_paths.append(save_map(image, "map1_dem_watershed.png"))

    positive_flow = np.where(valid_mask & np.isfinite(flow_accumulation) & (flow_accumulation > 0), flow_accumulation, 0)
    flow_values = np.log10(np.maximum(positive_flow, 1))
    flow_rgb = np.stack(
        [
            np.interp(flow_values, (0, max(float(flow_values.max()), 1)), (247, 8)),
            np.interp(flow_values, (0, max(float(flow_values.max()), 1)), (251, 81)),
            np.interp(flow_values, (0, max(float(flow_values.max()), 1)), (255, 156)),
        ],
        axis=-1,
    ).astype("uint8")
    flow_rgb[~valid_mask | (positive_flow <= 0)] = (238, 243, 248)
    flow_rgb[boundary] = (215, 48, 39)
    image, draw = base_canvas("Flow Accumulation - Watershed")
    paste_raster(image, flow_rgb)
    draw = ImageDraw.Draw(image)
    draw_outlet(draw)
    add_colorbar(image, flow_values[valid_mask], "Accumulated cells (log)", "flow")
    output_paths.append(save_map(image, "map2_flow_accumulation.png"))

    widths = np.asarray(stream_widths, dtype="float32")
    image, draw = base_canvas("River Network - Line Width by Flow Accumulation")
    draw_watershed_outline(draw)
    draw_streams(draw, widths)
    draw_outlet(draw, color=(20, 20, 20))
    output_paths.append(save_map(image, "map3_river_network.png"))

    distances = np.asarray(profile_distance_km, dtype="float64")
    elevations = np.asarray(profile_elevation_m, dtype="float64")
    valid_profile = np.isfinite(distances) & np.isfinite(elevations)
    if not valid_profile.any():
        raise ValueError("The main-channel profile contains no finite distance/elevation samples.")
    distances, elevations = distances[valid_profile], elevations[valid_profile]
    image = Image.new("RGB", (1200, 720), "white")
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = 90, 90, 1120, 590
    draw.text((600, 34), "Longitudinal Profile - Main Channel", fill=(32, 32, 32), font=_font(25), anchor="mm")
    dmin, dmax = float(distances.min()), float(distances.max())
    emin, emax = float(elevations.min()), float(elevations.max())
    dmax = dmax if dmax > dmin else dmin + 1
    emax = emax if emax > emin else emin + 1
    for fraction in np.linspace(0, 1, 6):
        x = round(left + fraction * (right - left))
        y = round(bottom - fraction * (bottom - top))
        draw.line((x, top, x, bottom), fill=(225, 225, 225), width=1)
        draw.line((left, y, right, y), fill=(225, 225, 225), width=1)
        draw.text((x, bottom + 10), f"{dmin + fraction * (dmax - dmin):.0f}", fill=(32, 32, 32), font=tick_font, anchor="mt")
        draw.text((left - 10, y), f"{emin + fraction * (emax - emin):.0f}", fill=(32, 32, 32), font=tick_font, anchor="rm")
    profile_points = [
        (round(left + (distance - dmin) / (dmax - dmin) * (right - left)),
         round(bottom - (elevation - emin) / (emax - emin) * (bottom - top)))
        for distance, elevation in zip(distances, elevations)
    ]
    draw.line(profile_points, fill=(70, 130, 180), width=2)
    draw.rectangle((left, top, right, bottom), outline=(65, 65, 65), width=2)
    draw.text(((left + right) // 2, bottom + 48), "Distance from outlet (km)", fill=(32, 32, 32), font=font, anchor="mm")
    elevation_label = Image.new("RGBA", (120, 24), (255, 255, 255, 0))
    ImageDraw.Draw(elevation_label).text((2, 2), "Elevation (m)", fill=(32, 32, 32), font=small_font)
    elevation_label = elevation_label.rotate(90, expand=True)
    image.paste(elevation_label, (20, (top + bottom - elevation_label.height) // 2), elevation_label)
    output_paths.append(save_map(image, "map4_longitudinal_profile.png"))

    image, draw = base_canvas(f"Final Candidate Hydropower Sites (n={len(candidates)})")
    gray = np.mean(dem_rgb.astype("float32"), axis=2).astype("uint8")
    gray_rgb = np.repeat(gray[:, :, None], 3, axis=2)
    gray_rgb[~valid_mask] = (238, 243, 248)
    gray_rgb[boundary] = (215, 48, 39)
    paste_raster(image, gray_rgb)
    draw = ImageDraw.Draw(image)
    draw_streams(draw, np.full(len(streams), 1), color=(176, 196, 222))
    gradients = candidates["euclidean_gradient_pct"].to_numpy(dtype="float64")
    gradient_min, gradient_max = float(np.nanmin(gradients)), float(np.nanmax(gradients))
    gradient_span = gradient_max - gradient_min or 1
    for _, candidate in candidates.iterrows():
        upstream = map_point(candidate["upstream_x"], candidate["upstream_y"])
        downstream = map_point(candidate["downstream_x"], candidate["downstream_y"])
        draw.line((upstream, downstream), fill=(239, 108, 0), width=2)
        dx, dy = downstream[0] - upstream[0], downstream[1] - upstream[1]
        length = max(float(np.hypot(dx, dy)), 1)
        tip = downstream
        left_arrow = (round(tip[0] - 8 * dx / length - 4 * dy / length), round(tip[1] - 8 * dy / length + 4 * dx / length))
        right_arrow = (round(tip[0] - 8 * dx / length + 4 * dy / length), round(tip[1] - 8 * dy / length - 4 * dx / length))
        draw.polygon((tip, left_arrow, right_arrow), fill=(239, 108, 0))
        value = (float(candidate["euclidean_gradient_pct"]) - gradient_min) / gradient_span
        color = (
            round(np.interp(value, (0, 0.5, 1), (13, 204, 240))),
            round(np.interp(value, (0, 0.5, 1), (8, 71, 249))),
            round(np.interp(value, (0, 0.5, 1), (135, 120, 33))),
        )
        radius = int(np.clip(np.sqrt(max(float(candidate["delta_z_m"]), 1) / 2), 4, 11))
        draw.ellipse((upstream[0] - radius, upstream[1] - radius, upstream[0] + radius, upstream[1] + radius), fill=color, outline="black", width=1)
        draw.text((upstream[0], upstream[1] - radius - 8), str(int(candidate["reach_id"])), fill="black", font=small_font, anchor="ms")
    outlet = map_point(*outlet_xy)
    draw.polygon(((outlet[0], outlet[1] - 8), (outlet[0] - 7, outlet[1] + 6), (outlet[0] + 7, outlet[1] + 6)), fill="black")
    add_colorbar(image, gradients, "Euclidean gradient (%)", "gradient")
    output_paths.append(save_map(image, "map5_final_candidates.png"))

    return output_paths
