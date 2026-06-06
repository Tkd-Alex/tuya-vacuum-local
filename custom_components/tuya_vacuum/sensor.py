"""Sensor platform for Tuya Vacuum Local."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTime,
    UnitOfArea,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TuyaVacuumCoordinator

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: TuyaVacuumCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    sensors = [
        TuyaVacuumSensor(coordinator, entry, "battery", "Battery", PERCENTAGE, SensorDeviceClass.BATTERY),
        TuyaVacuumSensor(coordinator, entry, "clean_area", "Cleaning Area", UnitOfArea.SQUARE_METERS, None),
        TuyaVacuumSensor(coordinator, entry, "clean_time", "Cleaning Time", UnitOfTime.MINUTES, SensorDeviceClass.DURATION),
        TuyaVacuumSensor(coordinator, entry, "total_area", "Total Clean Area", UnitOfArea.SQUARE_METERS, None, SensorStateClass.TOTAL_INCREASING),
        TuyaVacuumSensor(coordinator, entry, "total_time", "Total Cleaning Time", UnitOfTime.MINUTES, SensorDeviceClass.DURATION, SensorStateClass.TOTAL_INCREASING),
        TuyaVacuumSensor(coordinator, entry, "total_count", "Total Cleaning Count", "times", None, SensorStateClass.TOTAL_INCREASING),
        
        # Maintenance (Diagnostic)
        TuyaVacuumSensor(coordinator, entry, "edge_brush", "Edge Brush Life", UnitOfTime.MINUTES, SensorDeviceClass.DURATION, None, EntityCategory.DIAGNOSTIC),
        TuyaVacuumSensor(coordinator, entry, "roll_brush", "Roll Brush Life", UnitOfTime.MINUTES, SensorDeviceClass.DURATION, None, EntityCategory.DIAGNOSTIC),
        TuyaVacuumSensor(coordinator, entry, "filter", "Filter Life", UnitOfTime.MINUTES, SensorDeviceClass.DURATION, None, EntityCategory.DIAGNOSTIC),
        TuyaVacuumSensor(coordinator, entry, "dust_cloth", "Dust Cloth Life", UnitOfTime.MINUTES, SensorDeviceClass.DURATION, None, EntityCategory.DIAGNOSTIC),
    ]
    
    async_add_entities(sensors)

class TuyaVacuumSensor(CoordinatorEntity, SensorEntity):
    """Vacuum sensor entity."""
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TuyaVacuumCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        unit: str | None = None,
        device_class: SensorDeviceClass | None = None,
        state_class: SensorStateClass | None = None,
        entity_category: EntityCategory | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_entity_category = entity_category
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get(self._key)
