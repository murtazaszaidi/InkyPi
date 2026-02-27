import os
import logging
from datetime import datetime
from .abstract_display import AbstractDisplay

logger = logging.getLogger(__name__)

class MockDisplay(AbstractDisplay):
    """Mock display for development without hardware."""
    
    def __init__(self, device_config):
        self.device_config = device_config
        resolution = device_config.get_resolution()
        self.width = resolution[0]
        self.height = resolution[1]
        self.output_dir = device_config.get_config('output_dir', 'mock_display_output')
        os.makedirs(self.output_dir, exist_ok=True)
        
    def initialize_display(self):
        """Initialize mock display (no-op for development)."""
        logger.info(f"Mock display initialized: {self.width}x{self.height}")
        
    def display_image(self, image, image_settings=[]):
        from PIL import ImageDraw
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(self.output_dir, f"display_{timestamp}.png")
        
        # Check for partial refresh regions and draw debug rectangles
        partial_refresh_regions = None
        for setting in image_settings:
            if isinstance(setting, dict) and 'partial_refresh_regions' in setting:
                partial_refresh_regions = setting['partial_refresh_regions']
                break
        
        if partial_refresh_regions:
            # Create a copy with debug rectangles showing partial refresh areas
            debug_image = image.copy()
            draw = ImageDraw.Draw(debug_image)
            for region in partial_refresh_regions:
                x = region.get('x', 0)
                y = region.get('y', 0)
                width = region.get('width', self.width)
                height = region.get('height', self.height)
                # Draw red rectangle around partial refresh region
                draw.rectangle([x, y, x + width, y + height], outline=(255, 0, 0), width=3)
                logger.info(f"Mock display: partial refresh region ({x},{y}) size {width}x{height}")
            debug_image.save(filepath, "PNG")
            debug_image.save(os.path.join(self.output_dir, 'latest.png'), "PNG")
        else:
            image.save(filepath, "PNG")
            image.save(os.path.join(self.output_dir, 'latest.png'), "PNG")
            logger.info("Mock display: full refresh")