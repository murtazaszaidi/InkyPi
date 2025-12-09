import inspect
import importlib
import logging
import sys

from display.abstract_display import AbstractDisplay
from PIL import Image
from pathlib import Path
from plugins.plugin_registry import get_plugin_instance

logger = logging.getLogger(__name__)

class WaveshareDisplay(AbstractDisplay):
    """
    Handles Waveshare e-paper display dynamically based on device type.

    This class loads the appropriate display driver dynamically based on the 
    `display_type` specified in the device configuration, allowing support for 
    multiple Waveshare EPD models.  

    The module drivers are in display.waveshare_epd.
    """

    def initialize_display(self):
        
        """
        Initializes the Waveshare display device.

        Retrieves the display type from the device configuration and dynamically 
        loads the corresponding Waveshare EPD driver from display.waveshare_epd.

        Raises:
            ValueError: If `display_type` is missing or the specified module is 
                        not found.
        """
        
        logger.info("Initializing Waveshare display")

        # get the device type which should be the model number of the device.
        display_type = self.device_config.get_config("display_type")  
        logger.info(f"Loading EPD display for {display_type} display")

        if not display_type:
            raise ValueError("Waveshare driver but 'display_type' not specified in configuration.")

        # Construct module path dynamically - e.g. "display.waveshare_epd.epd7in3e"
        module_name = f"display.waveshare_epd.{display_type}" 

        # Workaround for some Waveshare drivers using 'import epdconfig' causing import errors
        epd_dir = Path(__file__).parent / "waveshare_epd"
        if str(epd_dir) not in sys.path:
            sys.path.insert(0, str(epd_dir))

        try:
            # Dynamically load module
            epd_module = importlib.import_module(module_name)  
            self.epd_display = epd_module.EPD()
            # Workaround for init functions with inconsistent casing
            self.epd_display_init = getattr(self.epd_display, "Init", getattr(self.epd_display, "init", None))

            if not callable(self.epd_display_init):
                raise AttributeError("No Init/init method found")

            self.epd_display_init()

            display_args_spec = inspect.getfullargspec(self.epd_display.display)
            display_args = display_args_spec.args
        except ModuleNotFoundError:
            raise ValueError(f"Unsupported Waveshare display type: {display_type}")
        except AttributeError:
            raise ValueError(f"Display does not support required methods: {display_type}")

        self.bi_color_display = len(display_args_spec.args) > 2

        # update the resolution directly from the loaded device context
        if not self.device_config.get_config("resolution"):
            w, h = int(self.epd_display.width), int(self.epd_display.height)
            resolution = [w, h] if w >= h else [h, w]
            self.device_config.update_value(
                "resolution",
                resolution,
                write=True)


    def display_image(self, image, image_settings=[]):
        
        """
        Displays an image on the Waveshare display.

        The image has been processed by adjusting orientation, resizing, and converting it
        into the buffer format required for e-paper rendering.

        Args:
            image (PIL.Image): The image to be displayed.
            image_settings (list, optional): Additional settings to modify image rendering.
                Can include 'partial_refresh' dict with keys: 'x', 'y', 'width', 'height'

        Raises:
            ValueError: If no image is provided.
        """

        logger.info("Displaying image to Waveshare display.")
        if not image:
            raise ValueError(f"No image provided.")

        # Check if partial refresh is requested (supports both single region and multiple regions)
        partial_refresh_region = None
        partial_refresh_regions = None
        
        for setting in image_settings:
            if isinstance(setting, dict):
                if 'partial_refresh_regions' in setting:
                    partial_refresh_regions = setting['partial_refresh_regions']
                    break
                elif 'partial_refresh' in setting:
                    partial_refresh_region = setting['partial_refresh']
                    break

        # Assume device was in sleep mode.
        self.epd_display_init()

        # Check if display supports partial refresh
        has_partial_refresh = hasattr(self.epd_display, 'display_Partial') or hasattr(self.epd_display, 'displayPartial')

        # Handle multiple regions or single region partial refresh
        if (partial_refresh_regions or partial_refresh_region) and has_partial_refresh:
            # Use the appropriate method name
            display_partial_method = getattr(self.epd_display, 'display_Partial', getattr(self.epd_display, 'displayPartial', None))
            
            if display_partial_method:
                # Convert single region to list for uniform handling
                regions = partial_refresh_regions if partial_refresh_regions else [partial_refresh_region]
                
                for region in regions:
                    x = region.get('x', 0)
                    y = region.get('y', 0)
                    width = region.get('width', self.epd_display.width)
                    height = region.get('height', self.epd_display.height)
                    
                    x_end = x + width
                    y_end = y + height
                    
                    logger.info(f"Performing partial refresh: region ({x},{y}) to ({x_end},{y_end})")
                    display_partial_method(self.epd_display.getbuffer(image), x, y, x_end, y_end)
            else:
                logger.warning("Partial refresh not supported, falling back to full refresh")
                self.epd_display.Clear()
                self.epd_display.display(self.epd_display.getbuffer(image))
        else:
            # Full refresh mode
            # Clear residual pixels before updating the image.
            self.epd_display.Clear()

            # Display the image on the WS display.
            if not self.bi_color_display:
                self.epd_display.display(self.epd_display.getbuffer(image))
            else:
                color_image = Image.new('1', image.size, 255)
                self.epd_display.display(
                    self.epd_display.getbuffer(image),
                    self.epd_display.getbuffer(color_image)
                )

        # Put device into low power mode (EPD displays maintain image when powered off)
        logger.info("Putting Waveshare display into sleep mode for power saving.")
        self.epd_display.sleep()

