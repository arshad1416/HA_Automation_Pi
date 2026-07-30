# VIRTUAL SENSORS (Shared across all vehicle models)
VIRTUAL_SENSORS = {
    "api_vehicle_status": ("Operating Status", None, "mdi:car-info", None),
    "api_current_address": ("Vehicle Location (Address)", None, "mdi:map-marker", None),
    "api_trip_distance": ("Trip Distance", "km", "mdi:map-marker-distance", "distance"),
    "api_trip_avg_speed": ("Avg Trip Speed", "km/h", "mdi:speedometer-medium", "speed"),
    "api_trip_energy_used": ("Trip Energy Used", "kWh", "mdi:lightning-bolt", "energy"),
    "api_trip_efficiency": ("Trip Efficiency", "kWh/100km", "mdi:leaf-circle", None),
    "api_static_capacity": ("Battery Capacity (Design)", "kWh", "mdi:car-battery", "energy"),
    "api_static_range": ("Rated Range (Max)", "km", "mdi:map-marker-distance", "distance"),
    "api_soh_calculated": ("Battery Health (SOH Calculated)", "%", "mdi:heart-pulse", "battery"),
    "api_battery_degradation": ("Battery Degradation (SOH)", "kWh", "mdi:battery-minus", "energy"),
    "api_est_range_degradation": ("Battery Degradation Potential (Range - Reference)", "%", "mdi:battery-alert", None),
    "api_lifetime_efficiency": ("Lifetime Efficiency (Vehicle Average)", "kWh/100km", "mdi:leaf", None),
    "api_calc_max_range": ("Real-World Range (100% Full)", "km", "mdi:map-marker-path", "distance"),
    "api_calc_remain_range": ("Remaining Range (Based on Efficiency)", "km", "mdi:map-marker-distance", "distance"),
    "api_calc_range_per_percent": ("Range per 1% Battery", "km", "mdi:ruler", "distance"),
    "api_best_efficiency_band": ("Optimal Speed Band", None, "mdi:chart-bell-curve", None),
    "api_last_charge_start_soc": ("SOC at Plug-in (Last)", "%", "mdi:battery-arrow-down", "battery"),
    "api_last_charge_end_soc": ("SOC at Unplug (Last)", "%", "mdi:battery-arrow-up", "battery"),
    "api_last_charge_duration": ("Charging Duration (Last)", "min", "mdi:timer-sand", "duration"),
    "api_last_charge_energy": ("Grid Energy Drawn (Last)", "kWh", "mdi:flash", "energy"),
    "api_last_charge_efficiency": ("Actual Charging Efficiency (Last)", "%", "mdi:car-electric-outline", None),
    "api_last_charge_power": ("Avg Charging Power (Last)", "kW", "mdi:ev-plug-type2", "power"),
    "api_live_charge_power": ("Calculated Charging Power (Live)", "kW", "mdi:flash", "power"),
    "api_total_charge_cost_est": ("Total Charging Cost", "VNĐ", "mdi:cash-fast", "monetary"),
    "api_trip_charge_cost": ("Trip Charging Cost", "VNĐ", "mdi:cash-fast", "monetary"),
    "api_total_gas_cost": ("Equivalent Gasoline Cost", "VNĐ", "mdi:gas-station", "monetary"),
    "api_trip_gas_cost": ("Trip Gasoline Cost", "VNĐ", "mdi:gas-station", "monetary"),
    "api_total_charge_sessions": ("Total Charging Sessions", "sessions", "mdi:battery-charging-100", None),
    "api_public_charge_sessions": ("Station Charging Sessions", "sessions", "mdi:ev-station", None),
    "api_home_charge_sessions": ("Home Charging Sessions", "sessions", "mdi:home-lightning-bolt-outline", None),
    "api_home_charge_kwh": ("Home Charging Energy", "kWh", "mdi:home-battery", "energy"),
    "api_total_energy_charged": ("Total Energy Charged", "kWh", "mdi:lightning-bolt", "energy"),
    "api_vehicle_model": ("Vehicle Model", None, "mdi:car", None),
    "api_vehicle_name": ("Vehicle Name", None, "mdi:account-car", None),
    "api_outside_temp": ("Outside Temperature", "°C", "mdi:thermometer", "temperature"),
    "api_weather_condition": ("Current Weather", None, "mdi:weather-partly-cloudy", None),
    "api_hvac_load_estimate": ("AC Load Estimate", None, "mdi:air-conditioner", None),
    "api_ai_advisor": ("AI EV Advisor", None, "mdi:robot-outline", None),
    "api_vehicle_image": ("Vehicle Image URL", None, "mdi:image", None),
    "api_trip_route": ("GPS Route", None, "mdi:map-marker-path", None),
    "api_nearby_stations": ("Nearby Charging Stations", None, "mdi:ev-station", None),
    "api_security_warning": ("Security Warning", None, "mdi:shield-alert", None),
    "api_debug_raw": ("System Debug Raw", None, "mdi:bug", None)
}

# COMMON SENSORS (All VF3, VF5, 6, 7, e34, VF8, VF9 vehicles)
COMMON_SENSORS = {
    "00006_00001_00000": ("Latitude", "°", "mdi:crosshairs-gps", None),
    "00006_00001_00001": ("Longitude", "°", "mdi:crosshairs-gps", None),
    "00006_00001_00002": ("Altitude", "m", "mdi:elevation-rise", None),
    "00005_00001_00030": ("Software Version (FRP)", None, "mdi:update", None),
    "34196_00001_00004": ("T-Box Version", None, "mdi:cellphone-link", None),
    "34181_00001_00007": ("License Plate / Secondary Name", None, "mdi:card-text-outline", None),
    
    "34213_00001_00003": ("Master Lock", None, "mdi:lock", None),
    "34234_00001_00003": ("Security Status", None, "mdi:shield-car", None),
    "34186_00005_00004": ("Hazard Lights", None, "mdi:car-light-alert", None),
    "34205_00001_00001": ("Valet Mode", None, "mdi:account-tie-hat", None),
    "34206_00001_00001": ("Camp Mode", None, "mdi:tent", None),
    "34207_00001_00001": ("Pet Mode", None, "mdi:paw", None),

    "10351_00002_00050": ("Driver Door", None, "mdi:car-door", None),
    "10351_00001_00050": ("Passenger Door", None, "mdi:car-door", None),
    "10351_00006_00050": ("Trunk", None, "mdi:car-door", None),
    "10351_00005_00050": ("Hood", None, "mdi:car-door", None),
    "34215_00002_00002": ("Driver Window", None, "mdi:window-open", None),
    "34215_00001_00002": ("Passenger Window", None, "mdi:window-open", None),
    
    "34213_00003_00003": ("Window Motor Status", None, "mdi:car-door-window", None),
    "34213_00002_00003": ("Trunk Motor Status", None, "mdi:car-back", None),

    "34213_00004_00003": ("Headlight Flash Status", None, "mdi:car-light-high", None),
    "34184_00001_00004": ("AC Status", None, "mdi:air-conditioner", None),
    "34184_00001_00011": ("Air Intake Mode", None, "mdi:car-windshield-outline", None),
    "34184_00001_00012": ("AC Air Direction", None, "mdi:fan", None),
    "34184_00001_00009": ("Defrost", None, "mdi:car-defrost-front", None),
    "34184_00001_00025": ("Fan Speed", "Level", "mdi:fan-speed-1", None),
    "34184_00001_00041": ("Cooling Level", "Level", "mdi:snowflake", None),
}

# LỚP CỘNG THÊM DÀNH CHO XE CÓ 4 CỬA
REAR_DOORS_WINDOWS = {
    "10351_00004_00050": ("Rear Left Door", None, "mdi:car-door", None),
    "10351_00003_00050": ("Rear Right Door", None, "mdi:car-door", None),
    "34215_00004_00002": ("Rear Left Window", None, "mdi:window-open", None),
    "34215_00003_00002": ("Rear Right Window", None, "mdi:window-open", None),
}

# PLATFORM A BASE (VF3, VF5, e34, VF6, VF7)
PLATFORM_A_BASE = COMMON_SENSORS.copy()
PLATFORM_A_BASE.update({
    "34183_00001_00009": ("Battery Level", "%", "mdi:battery", "battery"),
    "34183_00001_00011": ("Estimated Range", "km", "mdi:map-marker-distance", "distance"),
    "34183_00001_00001": ("Gear Position", None, "mdi:car-shift-pattern", None),
    "34183_00001_00002": ("Current Speed", "km/h", "mdi:speedometer", "speed"),
    "34183_00001_00003": ("Odometer", "km", "mdi:counter", "distance"),
    "34183_00001_00010": ("Drive Status (Ready)", None, "mdi:car-key", None), 
    
    "34183_00001_00029": ("Electronic Parking Brake", None, "mdi:car-brake-parking", None),
    "34183_00001_00035": ("Brake Pedal Switch", None, "mdi:car-brake-fluid-level", None),
    
    "34183_00001_00005": ("Pin 12V (Ắc quy)", "%", "mdi:car-battery", "battery"),
    "34220_00001_00001": ("Battery Health (SOH)", "%", "mdi:heart-pulse", "battery"),
    
    "34193_00001_00031": ("Charging Plug", None, "mdi:ev-plug-type2", None),
    "34193_00001_00005": ("Charging Status", None, "mdi:ev-station", None), 
    "34193_00001_00007": ("Charging Time Remaining", "min", "mdi:timer-outline", "duration"),
    
    "34193_00001_00026": ("Estimated Charging Time", "min", "mdi:timer-sand", "duration"),
    "34193_00001_00013": ("Estimated Charge Completion Time", None, "mdi:clock-check-outline", None),
    "34193_00001_00032": ("Charging System Relay", None, "mdi:electric-switch", None),
    "34193_00001_00016": ("Charging Session ID", None, "mdi:identifier", None),
    
    "34183_00001_00007": ("Outside Temperature", "°C", "mdi:thermometer", "temperature"),
    "34183_00001_00015": ("Inside Temperature", "°C", "mdi:thermometer", "temperature"),
    "34224_00001_00005": ("AC Temperature Setting", "°C", "mdi:thermostat", "temperature"),
})

# BỘ MÃ CHUYÊN BIỆT CHO NỀN TẢNG A (VF5, VF6, VF7, VF e34)
PLATFORM_VF567_SENSORS = PLATFORM_A_BASE.copy()
PLATFORM_VF567_SENSORS.update(REAR_DOORS_WINDOWS)

# Fix for duplicate Door Lock sensors on VF6
if "34213_00001_00003" in PLATFORM_VF567_SENSORS:
    del PLATFORM_VF567_SENSORS["34213_00001_00003"]

PLATFORM_VF567_SENSORS.update({
    "56789_00001_00005": ("Headlight Status", None, "mdi:car-light-high", None),
    "34206_00001_00001": ("Master Lock", None, "mdi:lock", None), 
})

# PLATFORM B BASE (VF8, VF9)
PLATFORM_B_BASE = COMMON_SENSORS.copy()
PLATFORM_B_BASE.update(REAR_DOORS_WINDOWS) 
PLATFORM_B_BASE.update({
    "34180_00001_00011": ("Battery Level", "%", "mdi:battery", "battery"),
    "34180_00001_00007": ("Estimated Range", "km", "mdi:map-marker-distance", "distance"),
    "34187_00000_00000": ("Gear Position", None, "mdi:car-shift-pattern", None),
    "34188_00000_00000": ("Current Speed", "km/h", "mdi:speedometer", "speed"),
    "34199_00000_00000": ("Odometer", "km", "mdi:counter", "distance"),
    "34180_00001_00010": ("Drive Status (Ready)", None, "mdi:car-key", None),
    "34181_00000_00000": ("Pin 12V (Ắc quy)", "%", "mdi:car-battery", "battery"),
    
    "34183_00000_00001": ("Charging Status", None, "mdi:ev-station", None),
    "34183_00000_00004": ("Charging Plug", None, "mdi:ev-plug-type2", None),
    "34183_00000_00009": ("Charging Time Remaining", "min", "mdi:timer-outline", "duration"),
    "34183_00000_00012": ("Charging Power (Station)", "kW", "mdi:flash", "power"),
    
    "34189_00000_00000": ("Outside Temperature", "°C", "mdi:thermometer", "temperature"),
    "34190_00000_00000": ("Inside Temperature", "°C", "mdi:thermometer", "temperature"),
})