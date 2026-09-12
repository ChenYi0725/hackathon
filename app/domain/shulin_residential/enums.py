"""Categories used by the Shulin ordinary-residential regional-factor schedule.

Enum values are the wording printed in the 備註 column of
《新北市樹林區普通住宅用地影響地價區域因素評價基準明細表》pages 4-26 to 4-30,
so that persisted values stay readable and no magic strings leak into the grading
functions.
"""
from enum import Enum


class GradeLabel(str, Enum):
    """優劣等級標籤，由最優排到最劣。

    Covers the 2／3／5／7-grade schemes used by this Shulin ordinary-residential
    ruleset. Labels belonging only to other schedules are deliberately omitted.
    """
    EXTREMELY_EXCELLENT = '極優'
    EXCELLENT = '優'
    SLIGHTLY_BETTER = '稍優'
    NORMAL = '普通'
    SLIGHTLY_WORSE = '稍劣'
    POOR = '劣'
    EXTREMELY_POOR = '極劣'


class LandUseCategory(str, Enum):
    """使用分區／使用地類別。"""
    COMMERCIAL_ZONE = '商業區'
    MRT_JOINT_DEVELOPMENT_LAND = '捷運用地（聯開）'
    RESIDENTIAL_ZONE = '住宅區'
    MARKET_LAND = '市場用地'
    CLASS_A_BUILDING_LAND = '甲建'
    CLASS_B_BUILDING_LAND = '乙建'
    SPECIFIC_PURPOSE_ZONE = '特定專用區'
    MULTI_PURPOSE_PUBLIC_FACILITY_LAND = '多目標使用之其他公共設施用地'
    INDUSTRIAL_ZONE = '工業區'
    CLASS_C_BUILDING_LAND = '丙建'
    CLASS_D_BUILDING_LAND = '丁建'
    OTHER_BUILDABLE_LAND = '其他可建築用地'


class BuildingRestriction(str, Enum):
    """有無限制建築。"""
    NO_RESTRICTION = '無限制建築'
    PARTIAL_RESTRICTION = '部分限制建築'
    OVERALL_DEVELOPMENT_RESTRICTION = '限制整體開發'


class RoadDevelopmentLevel(str, Enum):
    """區段內道路規劃及闢建程度。"""
    FULLY_PLANNED_AND_DEVELOPED = '全部規劃及闢建'
    MOSTLY_PLANNED_AND_DEVELOPED = '大部分規劃及闢建'
    PARTIALLY_PLANNED_AND_DEVELOPED = '部分規劃及闢建'
    GRAVEL_ROAD = '砂石路'
    NOT_PLANNED_OR_DEVELOPED = '全無規劃及闢建'


class SunlightLevel(str, Enum):
    """日照。"""
    FULL = '充分'
    SLIGHT_SHADE = '少許有陰雨'
    PARTIAL_SHADE = '有部分陰雨'
    CONSIDERABLE_SHADE = '有相當陰雨'
    MOSTLY_SHADED = '大部分陰雨'


class LandscapeLevel(str, Enum):
    """景觀。"""
    EXTREMELY_WIDE_AND_BEAUTIFUL = '視野極寬廣、景觀極優美'
    WIDE_AND_BEAUTIFUL = '視野寬廣、景觀優美'
    ACCEPTABLE = '視野、景觀尚可'
    POOR = '視野、景觀差'
    EXTREMELY_POOR = '視野、景觀極差'


class DrainageLevel(str, Enum):
    """排水之良否。"""
    EXTREMELY_COMPLETE = '極完善'
    HIGHLY_COMPLETE = '非常完善'
    ORDINARY_COMPLETE = '普通完善'
    INADEQUATE = '不良'
    EXTREMELY_INADEQUATE = '極不良'


class TerrainLevel(str, Enum):
    """地勢。"""
    EXTREMELY_FLAT_AND_FIRM = '極平坦堅硬'
    FLAT = '平坦地'
    GENTLE_SLOPE = '緩傾斜地'
    LOWLAND_OR_WETLAND = '低地、濕地'
    ISOLATED_AND_POOR = '地勢孤劣地'


class ImprovementType(str, Enum):
    """建築基地改良或其他改良項目。不含農地改良。"""
    SITE_LEVELING = '整平或填挖基地'
    DITCH_EXCAVATION = '開挖水溝'
    SOIL_AND_WATER_CONSERVATION = '水土保持'
    ROAD_PAVING = '鋪築道路'
    PIPE_LAYING = '埋設管道'
    RETAINING_WALL = '修築駁嵌'
    OTHER = '其他'
