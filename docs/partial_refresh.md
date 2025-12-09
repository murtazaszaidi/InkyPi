# Partial Refresh for E-Ink Displays

## Overview

Partial refresh allows updating only a specific region of an e-ink display instead of refreshing the entire screen. This feature provides several benefits:

- **Reduced flickering**: Only the updated region flashes
- **Faster updates**: Less data to transfer and process
- **Extended display lifespan**: Fewer full refresh cycles
- **Better user experience**: Less distracting for clock/status displays

## Supported Displays

Partial refresh is currently supported for Waveshare e-ink displays that have a `display_Partial()` or `displayPartial()` method. Confirmed compatible models:

- **epd7in5_V2** (7.5" V2) ✓
- Check Waveshare documentation for your specific model

## Configuration

### Plugin-Level Configuration

Add `image_settings` to your plugin's `plugin-info.json`:

```json
{
  "display_name": "Your Plugin",
  "id": "your_plugin",
  "class": "YourPlugin",
  "image_settings": [
    {
      "partial_refresh": {
        "x": 0,
        "y": 0,
        "width": 400,
        "height": 150
      }
    }
  ]
}
```

### Parameters

- **x**: X-coordinate of the top-left corner (pixels)
- **y**: Y-coordinate of the top-left corner (pixels)
- **width**: Width of the refresh region (pixels)
- **height**: Height of the refresh region (pixels)

### Important Notes

1. **Alignment**: Some displays require the X coordinates to be aligned to 8-pixel boundaries. The Waveshare driver handles this automatically.

2. **Full Refresh Fallback**: If the display doesn't support partial refresh, it will automatically fall back to a full refresh.

3. **Ghosting Prevention**: Even with partial refresh enabled, you should perform periodic full refreshes (every 10-20 cycles) to prevent ghosting. This is not yet automated.

## Example: Azan Plugin

The Azan plugin uses partial refresh to update only the current time display (top 150 pixels):

```json
{
  "display_name": "Azan",
  "id": "azan",
  "class": "Azan",
  "image_settings": [
    {
      "partial_refresh": {
        "x": 0,
        "y": 0,
        "width": 400,
        "height": 150
      }
    }
  ]
}
```

This configuration refreshes only the time area while keeping the prayer times static, reducing flicker and improving the display experience.

### Intelligent Full Refresh

The Azan plugin automatically detects when the date changes (at midnight) and performs a **full screen refresh** to update the prayer times for the new day. This ensures:

- **Normal updates** (every 60 seconds): Only the current time refreshes (partial refresh)
- **Midnight updates**: Full screen refreshes to show new prayer times
- **Manual date changes**: Full refresh when a custom date is selected

This smart behavior gives you the best of both worlds - minimal flicker during the day, with proper updates when the content actually changes.

## Determining the Refresh Region

To find the optimal refresh region for your plugin:

1. **Identify the dynamic content area**: What part of your display changes frequently?
2. **Measure the coordinates**: Use your image dimensions to determine the bounding box
3. **Add padding**: Include a small margin (10-20 pixels) to avoid edge artifacts
4. **Test**: Verify the region covers all changing content

### Tips

- For clocks: Typically the time display area (often top or center)
- For status displays: The status text region
- Avoid partial refresh if more than 50% of the screen changes regularly

## Device Configuration

To enable partial refresh on your Raspberry Pi with a Waveshare display:

1. **Set display_type** in `device.json`:
```json
{
  "display_type": "epd7in5_V2",
  ...
}
```

2. **Install the display driver** (done automatically during installation if using `-W` flag):
```bash
sudo ./install/install.sh -W epd7in5_V2
```

## Troubleshooting

### Partial refresh not working

1. Check if your display model supports partial refresh
2. Verify the `display_type` in `device.json` matches your hardware
3. Check logs for "Partial refresh not supported" warnings
4. Ensure the Waveshare driver is correctly installed

### Ghosting or artifacts

1. The refresh region might be too small - increase the area
2. Perform a full refresh by temporarily removing the `partial_refresh` setting
3. Consider implementing periodic full refreshes (every 10-20 updates)

### Performance issues

1. If partial refresh is slower than expected, the region might be too large
2. Ensure X coordinates are aligned to 8-pixel boundaries
3. Check system logs for SPI communication errors

## Future Enhancements

- Automatic full refresh scheduling (every N partial refreshes)
- Runtime toggle between full and partial refresh
- Per-instance partial refresh configuration via UI
- Support for multiple refresh regions
