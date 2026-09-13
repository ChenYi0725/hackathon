"""Allowlisted domain functions consume observations supplied outside the model."""
from app.domain.calculations import (
    calculate_average_road_width, calculate_building_density, calculate_straight_line_distance,
)

METHODS = {
    'average_road_width': (calculate_average_road_width, ('opened_road_widths_m',), 'm'),
    'building_density': (calculate_building_density, ('built_land_area_m2', 'section_total_area_m2'), '%'),
    'straight_line_distance': (calculate_straight_line_distance, ('coordinates_m',), 'm'),
}


def calculate_measurement(observations, method):
    function, required, unit = METHODS[method]
    missing = [key for key in required if getattr(observations, key) is None]
    if missing:
        return dict(status='missing', missing_fields=missing, method=method)
    args = [getattr(observations, key) for key in required]
    result = function(*args[0]) if method == 'straight_line_distance' else function(*args)
    return dict(status='preview', method=method, function=function.__name__, unit=unit,
                inputs=observations.model_dump(mode='json', include=set(required)), result=str(result),
                input_source='user-supplied-measurements', rounding='none',
                warning='待核對量測值、規範適用性與方法；尚未套用或確認案件欄位。')
