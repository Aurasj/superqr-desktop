class V6DisplayMetrics:
    def __init__(self, contract: dict, scale: float):
        b_bbox = contract["border"]["bbox"]
        self.active_width = int((b_bbox[2] - b_bbox[0]) * scale)
        self.active_height = int((b_bbox[3] - b_bbox[1]) * scale)
        
        g_bbox = contract["data_grid"]["bbox"]
        self.grid_width = int((g_bbox[2] - g_bbox[0]) * scale)
        self.grid_height = int((g_bbox[3] - g_bbox[1]) * scale)
