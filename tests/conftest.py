# conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pandas as pd
import requests
from backend.storage.database import VectorDB, Base
from backend.schemas.models import AthleteState, RaceEvent, TrainingBlock, ContextAssembler, WorkoutStep, Session, WeekPlan

# In-memory SQLite database for testing
engine = create_engine(
    'sqlite:///:memory:',
    connect_args={'check_same_thread': False},
    poolclass=StaticPool
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

@pytest.fixture(scope="module")
def db():
    # Create the database and tables
    db = VectorDB(engine)
    yield db
    # Rollback any transactions to ensure a clean state for each test
    db.session.rollback()

@pytest.fixture(scope="function")
def sample_daily_tss_series():
    data = pd.Series([10, 20, 30, 40, 50])
    return data

@pytest.fixture(scope="function")
def sample_swim_times():
    times = [{"distance": 100, "time": 50}, {"distance": 200, "time": 100}]
    return times

@pytest.fixture(scope="function")
def ollama_api_response():
    response = {
        "status": "success",
        "data": {"result": "mocked data"}
    }
    return response

@pytest.fixture(scope="function")
def athlete_state_fixture():
    state = AthleteState(id=1, name="Test Athlete")
    return state

@pytest.fixture(scope="function")
def race_event_fixture():
    event = RaceEvent(id=1, name="Test Race")
    return event

@pytest.fixture(scope="function")
def training_block_fixture():
    block = TrainingBlock(id=1, name="Test Block")
    return block

@pytest.fixture(scope="function")
def context_assembler_fixture():
    assembler = ContextAssembler(id=1, name="Test Assembler")
    return assembler

@pytest.fixture(scope="function")
def valid_workout_step_data():
    data = {
        "name": "Warm Up",
        "type": "Run",
        "duration": 30
    }
    return data

@pytest.fixture(scope="function")
def invalid_workout_step_data():
    data = {
        "name": "",
        "type": "Swim",
        "duration": -10
    }
    return data

@pytest.fixture(scope="function")
def valid_session_data():
    data = {
        "date": "2023-04-01",
        "workout_steps": [{"name": "Warm Up", "type": "Run", "duration": 30}]
    }
    return data

@pytest.fixture(scope="function")
def invalid_session_data():
    data = {
        "date": "",
        "workout_steps": [{"name": "Warm Up", "type": "Swim", "duration": -10}]
    }
    return data

@pytest.fixture(scope="function")
def valid_week_plan_data():
    data = {
        "start_date": "2023-04-01",
        "sessions": [{"date": "2023-04-01", "workout_steps": [{"name": "Warm Up", "type": "Run", "duration": 30}]}]
    }
    return data

@pytest.fixture(scope="function")
def invalid_week_plan_data():
    data = {
        "start_date": "",
        "sessions": [{"date": "", "workout_steps": [{"name": "Warm Up", "type": "Swim", "duration": -10}]}]
    }
    return data