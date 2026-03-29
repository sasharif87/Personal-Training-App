import pytest
from pydantic import ValidationError
from backend.schemas.workout import WorkoutStep, Session, WeekPlan

# Test cases for WorkoutStep model
class TestWorkoutStep:
    def test_valid_workout_step(self, valid_workout_step_data):
        workout_step = WorkoutStep(**valid_workout_step_data)
        assert workout_step.type == "interval"
        assert workout_step.duration_sec is None
        assert workout_step.distance_m is None
        assert workout_step.target_value == 0.8
        assert workout_step.target_type == "power"
        assert workout_step.repeat == 1
        assert workout_step.description is None

    def test_invalid_workout_step(self, invalid_workout_step_data):
        with pytest.raises(ValidationError):
            WorkoutStep(**invalid_workout_step_data)

# Test cases for Session model
class TestSession:
    def test_valid_session(self, valid_session_data):
        session = Session(**valid_session_data)
        assert session.sport == "bike"
        assert session.title == "Long Ride"
        assert session.description == "A long bike ride to prepare for a race."
        assert session.rationale == "Prepare for upcoming races."
        assert len(session.steps) == 2
        for step in session.steps:
            assert isinstance(step, WorkoutStep)

    def test_invalid_session(self, invalid_session_data):
        with pytest.raises(ValidationError):
            Session(**invalid_session_data)

# Test cases for WeekPlan model
class TestWeekPlan:
    def test_valid_week_plan(self, valid_week_plan_data):
        week_plan = WeekPlan(**valid_week_plan_data)
        assert week_plan.week_number == 1
        assert week_plan.block_phase == "build"
        assert len(week_plan.sessions) == 3
        for session in week_plan.sessions:
            assert isinstance(session, Session)

    def test_invalid_week_plan(self, invalid_week_plan_data):
        with pytest.raises(ValidationError):
            WeekPlan(**invalid_week_plan_data)