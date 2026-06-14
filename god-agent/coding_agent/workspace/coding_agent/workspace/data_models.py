# Data models for Indian Rail API

class Train:
    def __init__(self, train_id, name):
        self.train_id = train_id
        self.name = name

class Station:
    def __init__(self, station_id, name):
        self.station_id = station_id
        self.name = name

class ScheduleEntry:
    def __init__(self, train, station, arrival_time, departure_time):
        self.train = train
        self.station = station
        self.arrival_time = arrival_time
        self.departure_time = departure_time

class DelayInfo:
    def __init__(self, train, delay_minutes):
        self.train = train
        self.delay_minutes = delay_minutes

class WeatherInfo:
    def __init__(self, station, weather_conditions):
        self.station = station
        self.weather_conditions = weather_conditions

class TrackStatusInfo:
    def __init__(self, station, track_status):
        self.station = station
        self.track_status = track_status