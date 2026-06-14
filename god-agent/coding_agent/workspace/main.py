from mock_data_fetcher import MockDataFetcher
from optimization_engine import OptimizationEngine
from schedule_recalculator import ScheduleRecalculator
from rerouting_planner import ReroutingPlanner

data_fetcher = MockDataFetcher()
optimization_engine = OptimizationEngine(data_fetcher)
schedule_recalculator = ScheduleRecalculator(data_fetcher, optimization_engine)
rerouting_planner = ReroutingPlanner(data_fetcher)

print(optimization_engine.optimize_schedules())
print(schedule_recalculator.recalculate_schedules())
print(rerouting_planner.plan_rerouting())