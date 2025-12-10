"""
Azan Plugin for InkyPi
This plugin calculates Islamic prayer timings offline using the praytimes library
and displays them on the InkyPi device.

Uses praytimes library for offline prayer time calculations.
The plugin supports custom location (latitude/longitude), calculation methods, and date selection.

Flow:

1. Determine the date to use for prayer timings based on settings. (_determine_date)
2. Calculate prayer timings locally using coordinates and timezone. (_calculate_prayer_timings)
3. Render the timings as an image. (_render_timings_image)
"""

from plugins.base_plugin.base_plugin import BasePlugin
from PIL import Image, ImageDraw, ImageFont, ImageChops
import logging
import os
import threading
import subprocess
from datetime import datetime, date, time, timedelta
from typing import Dict, Any, List
import praytimes
import pytz
import numpy as np

logger = logging.getLogger(__name__)

class Azan(BasePlugin):
    # Class variable to track if monitoring thread is running
    _monitoring_thread = None
    _stop_monitoring = False
    _last_played_prayer = None
    _previous_image = None  # Store previous image for differential refresh
    _last_date_displayed = None  # Track the last date for full refresh detection

    def generate_settings_template(self) -> Dict[str, Any]:
        template_params = super().generate_settings_template()
        template_params['style_settings'] = False
        return template_params

    def generate_image(self, settings: Dict[str, Any], device_config: Dict[str, Any]) -> Image.Image:
        logger.info(f"Azan plugin settings: {settings}")
        
        # Get the date to fetch prayer timings for
        date_to_fetch = self._determine_date(settings)
        logger.info(f"Azan plugin date to fetch: {date_to_fetch}")

        # Get coordinates, timezone, and method from settings
        latitude = float(settings.get("latitude", "29.7604"))  # Houston default
        longitude = float(settings.get("longitude", "-95.3698"))  # Houston default
        timezone_str = settings.get("timezone", "America/Chicago")  # Houston default
        method = settings.get("method", "0")  # Default to Shia Ithna-Ashari method
        
        # Calculate prayer timings locally
        timings_data = self._calculate_prayer_timings(date_to_fetch, latitude, longitude, timezone_str, method)
        logger.info(f"Azan plugin timings calculated: {timings_data}")

        # Play adhan on refresh if enabled
        if settings.get("play_on_refresh", "false") == "true":
            logger.info("Playing adhan on refresh")
            threading.Thread(target=self._play_adhan, args=(settings,), daemon=True).start()

        # Start monitoring thread if enabled and not already running
        if settings.get("enable_adhan", "false") == "true":
            self._start_prayer_monitoring(timings_data, settings)
        
        # Get device dimensions
        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]
        width, height = dimensions

        # Render the prayer timings as an image
        image = self._render_timings_image(timings_data, width, height, date_to_fetch)
        
        # Check if date changed - if so, force full refresh
        date_changed = Azan._last_date_displayed != date_to_fetch
        if date_changed:
            logger.info(f"Date changed from {Azan._last_date_displayed} to {date_to_fetch}, forcing full refresh")
            Azan._last_date_displayed = date_to_fetch
            # Clear previous image to force full refresh
            Azan._previous_image = None
        
        # Simulate the rotation that will happen in display_manager to compare in final form
        from utils.image_utils import change_orientation
        rotated_image = change_orientation(image.copy(), device_config.get_config("orientation"))
        
        # Perform differential refresh if we have a previous image
        if Azan._previous_image is not None and not date_changed:
            try:
                # Compare the rotated images (final form)
                # Use smaller padding (4px) and min box size (16px) for more precise updates
                changed_regions = self._detect_changed_regions(
                    Azan._previous_image, 
                    rotated_image,
                    min_box_size=16,
                    padding=4
                )
                if changed_regions:
                    logger.info(f"Detected {len(changed_regions)} changed region(s) for differential refresh")
                    for region in changed_regions:
                        logger.info(f"  Region: ({region['x']},{region['y']}) size {region['width']}x{region['height']}")
                    # Override image_settings with detected regions
                    self.config["image_settings"] = [{"partial_refresh_regions": changed_regions}]
                else:
                    logger.info("No pixel changes detected, skipping refresh entirely")
                    # Return None or previous image to signal no refresh needed
            except Exception as e:
                logger.error(f"Error in differential refresh detection: {e}", exc_info=True)
                # Fall back to configured partial refresh on error
        
        # Store current rotated image for next comparison
        Azan._previous_image = rotated_image.copy()
        
        return image

    def _determine_date(self, settings: Dict[str, Any]) -> date:
        if settings.get("customDate"):
            return datetime.strptime(settings["customDate"], "%Y-%m-%d").date()
        else:
            return datetime.today().date()

    def _calculate_prayer_timings(self, date_to_calculate: date, latitude: float, longitude: float, 
                                   timezone_str: str, method: str) -> Dict[str, Any]:
        """
        Calculate prayer timings locally using the praytimes library.
        """
        try:
            # Get timezone object
            tz = pytz.timezone(timezone_str)
            
            # Create datetime object for the date in the specified timezone
            dt = tz.localize(datetime.combine(date_to_calculate, datetime.min.time()))
            
            # Map method string to calculation method for praytimes
            method_map = {
                "0": "Jafari",  # Shia Ithna-Ashari
                "1": "Karachi",  # University of Islamic Sciences, Karachi
                "2": "ISNA",  # Islamic Society of North America
                "3": "MWL",  # Muslim World League
                "4": "Makkah",  # Umm Al-Qura University, Makkah
                "5": "Egypt",  # Egyptian General Authority of Survey
                "7": "Tehran",  # Institute of Geophysics, University of Tehran
                "8": "Makkah",  # Gulf Region (use Makkah)
                "9": "Makkah",  # Kuwait (use Makkah)
                "10": "Makkah",  # Qatar (use Makkah)
                "11": "ISNA",  # Singapore (use ISNA)
                "12": "MWL",  # France (use MWL)
                "13": "Turkey",  # Turkey
                "14": "MWL",  # Russia (use MWL)
            }
            
            calc_method = method_map.get(method, "Jafari")
            
            # Create PrayTimes instance
            PT = praytimes.PrayTimes(calc_method)
            
            # Get UTC offset in hours
            utc_offset = dt.utcoffset().total_seconds() / 3600
            
            # Calculate prayer times - praytimes expects (year, month, day) tuple
            date_tuple = (date_to_calculate.year, date_to_calculate.month, date_to_calculate.day)
            times = PT.getTimes(date_tuple, (latitude, longitude), utc_offset)
            
            # Ensure we have the standard names and format properly
            result_timings = {
                "Fajr": times.get("fajr", "00:00"),
                "Sunrise": times.get("sunrise", "00:00"),
                "Dhuhr": times.get("dhuhr", "00:00"),
                "Asr": times.get("asr", "00:00"),
                "Maghrib": times.get("maghrib", "00:00"),
                "Isha": times.get("isha", "00:00"),
                "Midnight": times.get("midnight", "00:00"),
            }
            
            return {"timings": result_timings, "date": {"readable": date_to_calculate.strftime("%d %B %Y")}}
            
        except Exception as e:
            logger.error(f"Failed to calculate prayer timings: {str(e)}", exc_info=True)
            raise RuntimeError(f"Failed to calculate prayer timings: {str(e)}")

    def _render_timings_image(self, timings_data: Dict[str, Any], width: int, height: int, 
                               date_obj: date) -> Image.Image:
        """
        Render the prayer timings as an image with a modern UI design.
        """
        # Create a white background
        bg_color = (255, 255, 255)  # White color
        image = Image.new("RGB", (width, height), bg_color)
        draw = ImageDraw.Draw(image)
        
        # Get the path to the Alata font file in the plugin directory
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        alata_font_path = os.path.join(plugin_dir, "Alata-Regular.ttf")
        
        # Load Alata font with different sizes
        try:
            # Very large font for current time
            time_font = ImageFont.truetype(alata_font_path, 100)
        except:
            try:
                # Fallback to Arial if Alata not found
                time_font = ImageFont.truetype("/Library/Fonts/Arial.ttf", 100)
            except:
                time_font = ImageFont.load_default()
        
        try:
            # Large font for prayer names
            prayer_name_font = ImageFont.truetype(alata_font_path, 50)
        except:
            try:
                prayer_name_font = ImageFont.truetype("/Library/Fonts/Arial.ttf", 50)
            except:
                prayer_name_font = ImageFont.load_default()
        
        try:
            # Medium-large font for prayer times
            prayer_time_font = ImageFont.truetype(alata_font_path, 45)
        except:
            try:
                prayer_time_font = ImageFont.truetype("/Library/Fonts/Arial.ttf", 45)
            except:
                prayer_time_font = ImageFont.load_default()
        
        # Extract timings
        timings = timings_data.get("timings", {})
        
        # Current time display at the top (LEFT ALIGNED with fixed AM/PM position)
        now_time = datetime.now()
        time_digits = now_time.strftime("%I:%M").lstrip("0")  # Remove leading zero
        am_pm = now_time.strftime("%p").lower()
        
        currentTimeLeftMargin = 30
        left_margin = 40
        time_y = 40
        
        # Draw current time digits (left aligned)
        draw.text((currentTimeLeftMargin, time_y), time_digits, fill=(0, 0, 0), font=time_font)
        
        # Draw AM/PM in fixed position (always at same X coordinate)
        # Calculate position: after "12:59" which is the widest time possible
        try:
            bbox = draw.textbbox((0, 0), "12:59", font=time_font)
            max_time_width = bbox[2] - bbox[0]
        except:
            max_time_width = 280  # Fallback estimate
        
        # Position AM/PM at a fixed location with some spacing
        am_pm_x = currentTimeLeftMargin + max_time_width + 20
        try:
            # Use smaller font for AM/PM
            am_pm_font = ImageFont.truetype(alata_font_path, 50)
        except:
            try:
                am_pm_font = ImageFont.truetype("/Library/Fonts/Arial.ttf", 50)
            except:
                am_pm_font = ImageFont.load_default()
        
        # Align AM/PM vertically with time (baseline alignment)
        draw.text((am_pm_x, time_y + 40), am_pm, fill=(0, 0, 0), font=am_pm_font)
        
        # Prayer timings layout
        y_start = time_y + 180
        left_col_x = left_margin
        right_col_x = width - 40
        
        # Get current time for comparison
        now = datetime.now().time()
        
        # Prayer names and times mapping
        prayers_to_show = [
            ("Fajr", "Fajr"),
            ("Sunrise", "Sunrise"),
            ("Dhuhr", "Zuhr"),
            ("Maghrib", "Maghrib"),
            ("Midnight", "Midnight")
        ]
        
        row_height = 100
        
        for i, (api_key, display_name) in enumerate(prayers_to_show):
            y_pos = y_start + (i * row_height)
            
            # Get the time for this prayer
            if api_key in timings:
                time_str = timings[api_key].split(" ")[0]  # Remove timezone
                # Convert to 12-hour format if needed
                try:
                    time_obj = datetime.strptime(time_str, "%H:%M")
                    prayer_time = time_obj.time()
                    time_str = time_obj.strftime("%I:%M").lstrip("0")
                    
                    # Determine if prayer time has passed
                    if now > prayer_time:
                        time_color = (128, 128, 128)  # Grey for past prayers
                    else:
                        time_color = (0, 0, 0)  # Black for upcoming prayers
                except:
                    time_color = (0, 0, 0)
                    pass
            else:
                time_str = "--:--"
                time_color = (128, 128, 128)
            
            # Draw prayer name (left aligned)
            draw.text((left_col_x, y_pos), display_name, fill=(0, 0, 0), font=prayer_name_font)
            
            # Draw time (right aligned)
            try:
                bbox = draw.textbbox((0, 0), time_str, font=prayer_time_font)
                time_text_width = bbox[2] - bbox[0]
            except:
                time_text_width = len(time_str) * 25
            
            draw.text((right_col_x - time_text_width, y_pos), time_str, fill=time_color, font=prayer_time_font)
        
        return image
    
    def _start_prayer_monitoring(self, timings_data: Dict[str, Any], settings: Dict[str, Any]):
        """Start a background thread to monitor prayer times and play adhan."""
        if Azan._monitoring_thread and Azan._monitoring_thread.is_alive():
            logger.info("Prayer monitoring thread already running")
            return
        
        Azan._stop_monitoring = False
        Azan._monitoring_thread = threading.Thread(
            target=self._monitor_prayer_times,
            args=(timings_data, settings),
            daemon=True
        )
        Azan._monitoring_thread.start()
        logger.info("Started prayer time monitoring thread")
    
    def _monitor_prayer_times(self, timings_data: Dict[str, Any], settings: Dict[str, Any]):
        """Monitor current time and play adhan when prayer time arrives."""
        timings = timings_data.get("timings", {})
        prayer_names = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
        
        logger.info("Prayer time monitoring thread started")
        
        while not Azan._stop_monitoring:
            try:
                now = datetime.now()
                current_time = now.strftime("%H:%M")
                current_key = f"{now.date()}_{current_time}"
                
                # Check each prayer time
                for prayer in prayer_names:
                    if prayer in timings:
                        prayer_time_str = timings[prayer].split(" ")[0]  # Remove timezone info
                        
                        # Check if current time matches prayer time
                        if current_time == prayer_time_str:
                            # Avoid playing multiple times for the same prayer in the same minute
                            if Azan._last_played_prayer != current_key:
                                logger.info(f"Prayer time reached: {prayer} at {current_time}")
                                self._play_adhan(settings)
                                Azan._last_played_prayer = current_key
                                break
                
                # Sleep for a few seconds before checking again
                import time
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                logger.error(f"Error in prayer monitoring thread: {str(e)}")
                import time
                time.sleep(10)
    
    def _play_adhan(self, settings: Dict[str, Any]):
        """Play the adhan audio file."""
        try:
            # Check for custom adhan audio file
            adhan_file = settings.get("adhan_audio")
            
            # Default adhan file location
            if not adhan_file:
                plugin_dir = os.path.dirname(os.path.abspath(__file__))
                adhan_file = os.path.join(plugin_dir, "adhan.mp3")
            
            if not os.path.exists(adhan_file):
                logger.warning(f"Adhan audio file not found: {adhan_file}")
                return
            
            logger.info(f"Playing adhan from: {adhan_file}")
            
            # Use afplay on macOS or mpg123/ffplay on Linux to play audio
            try:
                # Try macOS afplay first
                subprocess.run(["afplay", adhan_file], check=True, timeout=300)
            except (FileNotFoundError, subprocess.SubprocessError):
                try:
                    # Try mpg123 on Linux
                    subprocess.run(["mpg123", adhan_file], check=True, timeout=300)
                except (FileNotFoundError, subprocess.SubprocessError):
                    try:
                        # Try ffplay as fallback
                        subprocess.run(["ffplay", "-nodisp", "-autoexit", adhan_file], 
                                     check=True, timeout=300)
                    except (FileNotFoundError, subprocess.SubprocessError) as e:
                        logger.error(f"No audio player found. Install afplay, mpg123, or ffplay: {e}")
            
        except Exception as e:
            logger.error(f"Error playing adhan: {str(e)}")
    
    def _detect_changed_regions(self, previous_image: Image.Image, current_image: Image.Image, 
                                 min_box_size: int = 32, padding: int = 16) -> List[Dict[str, int]]:
        """
        Detect rectangular regions where pixels have changed between two images.
        Optimized for Waveshare e-ink displays with minimal refresh areas.
        
        Args:
            previous_image: The previous rendered image
            current_image: The current rendered image  
            min_box_size: Minimum size for a bounding box (both width and height)
            padding: Extra pixels to add around detected changes for visual quality
            
        Returns:
            List of dicts with keys: x, y, width, height representing changed regions
        """
        # Ensure images are the same size
        if previous_image.size != current_image.size:
            logger.warning("Image sizes don't match, cannot perform differential refresh")
            return []
        
        # Convert to grayscale for comparison
        prev_gray = previous_image.convert('L')
        curr_gray = current_image.convert('L')
        
        # Calculate pixel difference
        diff = ImageChops.difference(prev_gray, curr_gray)
        
        # Convert to numpy array for efficient processing
        diff_array = np.array(diff)
        
        # Find all pixels that changed (non-zero difference)
        changed_pixels = np.where(diff_array > 0)
        
        if len(changed_pixels[0]) == 0:
            logger.debug("No pixel changes detected")
            return []  # No changes detected
        
        # Get bounding box of all changes
        min_y, max_y = int(changed_pixels[0].min()), int(changed_pixels[0].max())
        min_x, max_x = int(changed_pixels[1].min()), int(changed_pixels[1].max())
        
        # Add padding around the changed region
        width, height = current_image.size
        min_x = max(0, min_x - padding)
        min_y = max(0, min_y - padding)
        max_x = min(width - 1, max_x + padding)
        max_y = min(height - 1, max_y + padding)
        
        # Calculate dimensions
        box_width = max_x - min_x + 1
        box_height = max_y - min_y + 1
        
        # Ensure minimum box size for display compatibility
        if box_width < min_box_size:
            expand = (min_box_size - box_width) // 2
            min_x = max(0, min_x - expand)
            max_x = min(width - 1, min_x + min_box_size - 1)
            box_width = max_x - min_x + 1
            
        if box_height < min_box_size:
            expand = (min_box_size - box_height) // 2
            min_y = max(0, min_y - expand)
            max_y = min(height - 1, min_y + min_box_size - 1)
            box_height = max_y - min_y + 1
        
        # Align X coordinates to 8-pixel boundaries (required by Waveshare displays)
        min_x = (min_x // 8) * 8
        # Adjust width to maintain coverage after alignment
        box_width = min(((box_width + 7) // 8) * 8, width - min_x)
        
        region = {
            "x": int(min_x),
            "y": int(min_y),
            "width": int(box_width),
            "height": int(box_height)
        }
        
        logger.debug(f"Changed region detected: x={region['x']}, y={region['y']}, " +
                    f"width={region['width']}, height={region['height']}")
        
        return [region]