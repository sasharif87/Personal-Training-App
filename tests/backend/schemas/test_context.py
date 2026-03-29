import pytest
from pydantic import ValidationError
from backend.schemas.context import AthleteState, RaceEvent, TrainingBlock, ContextAssembler

# Test cases for AthleteState model
class TestAthleteState:
    def test_valid_athlete_state(self):
        athlete_data = {
            "ftp": 300,
            "css": "2:15",
            "lthr_run": 160,
            "ctl": 7.5,
            "atl": 4.2,
            "tsb": -1.8,
            "hrv_trend": "normal"
        }
        athlete = AthleteState(**athlete_data)
        assert athlete.ftp == 300
        assert athlete.css == "2:15"
        assert athlete.lthr_run == 160
        assert athlete.ctl == 7.5
        assert athlete.atl == 4.2
        assert athlete.tsb == -1.8
        assert athlete.hrv_trend == "normal"

    def test_invalid_ftp(self):
        with pytest.raises(ValidationError):
            AthleteState(ftp="not an int", css="2:15", lthr_run=160, ctl=7.5, atl=4.2, tsb=-1.8, hrv_trend="normal")

    def test_invalid_css(self):
        with pytest.raises(ValidationError):
            AthleteState(ftp=300, css="not a time", lthr_run=160, ctl=7.5, atl=4.2, tsb=-1.8, hrv_trend="normal")

    def test_invalid_lthr_run(self):
        with pytest.raises(ValidationError):
            AthleteState(ftp=300, css="2:15", lthr_run="not an int", ctl=7.5, atl=4.2, tsb=-1.8, hrv_trend="normal")

    def test_invalid_ctl(self):
        with pytest.raises(ValidationError):
            AthleteState(ftp=300, css="2:15", lthr_run=160, ctl="not a float", atl=4.2, tsb=-1.8, hrv_trend="normal")

    def test_invalid_atl(self):
        with pytest.raises(ValidationError):
            AthleteState(ftp=300, css="2:15", lthr_run=160, ctl=7.5, atl="not a float", tsb=-1.8, hrv_trend="normal")

    def test_invalid_tsb(self):
        with pytest.raises(ValidationError):
            AthleteState(ftp=300, css="2:15", lthr_run=160, ctl=7.5, atl=4.2, tsb="not a float", hrv_trend="normal")

    def test_invalid_hrv_trend(self):
        with pytest.raises(ValidationError):
            AthleteState(ftp=300, css="2:15", lthr_run=160, ctl=7.5, atl=4.2, tsb=-1.8, hrv_trend="invalid trend")

# Test cases for RaceEvent model
class TestRaceEvent:
    def test_valid_race_event(self):
        race_data = {
            "date": "2023-05-01",
            "format": "Ironman",
            "priority": "A"
        }
        race = RaceEvent(**race_data)
        assert race.date == "2023-05-01"
        assert race.format == "Ironman"
        assert race.priority == "A"

    def test_invalid_date(self):
        with pytest.raises(ValidationError):
            RaceEvent(date="not a date", format="Ironman", priority="A")

    def test_invalid_format(self):
        with pytest.raises(ValidationError):
            RaceEvent(date="2023-05-01", format="InvalidFormat", priority="A")

    def test_invalid_priority(self):
        with pytest.raises(ValidationError):
            RaceEvent(date="2023-05-01", format="Ironman", priority="InvalidPriority")

# Test cases for TrainingBlock model
class TestTrainingBlock:
    def test_valid_training_block(self):
        training_data = {
            "phase": "Build",
            "week_in_block": 4,
            "weeks_to_race": 12,
            "target_race": RaceEvent(date="2023-05-01", format="Ironman", priority="A")
        }
        block = TrainingBlock(**training_data)
        assert block.phase == "Build"
        assert block.week_in_block == 4
        assert block.weeks_to_race == 12
        assert block.target_race.date == "2023-05-01"
        assert block.target_race.format == "Ironman"
        assert block.target_race.priority == "A"

    def test_invalid_phase(self):
        with pytest.raises(ValidationError):
            TrainingBlock(phase="InvalidPhase", week_in_block=4, weeks_to_race=12, target_race=RaceEvent(date="2023-05-01", format="Ironman", priority="A"))

    def test_invalid_week_in_block(self):
        with pytest.raises(ValidationError):
            TrainingBlock(phase="Build", week_in_block="not an int", weeks_to_race=12, target_race=RaceEvent(date="2023-05-01", format="Ironman", priority="A"))

    def test_invalid_weeks_to_race(self):
        with pytest.raises(ValidationError):
            TrainingBlock(phase="Build", week_in_block=4, weeks_to_race="not an int", target_race=RaceEvent(date="2023-05-01", format="Ironman", priority="A"))

# Test cases for ContextAssembler model
class TestContextAssembler:
    def test_valid_context_assembler(self):
        context_data = {
            "athlete": AthleteState(ftp=300, css="2:15", lthr_run=160, ctl=7.5, atl=4.2, tsb=-1.8, hrv_trend="normal"),
            "block": TrainingBlock(phase="Build", week_in_block=4, weeks_to_race=12, target_race=RaceEvent(date="2023-05-01", format="Ironman", priority="A")),
            "yesterday_actual": {"activity": "Run", "distance": 10.5, "time": "45:30"},
            "retrieved_history": [{"activity": "Swim", "distance": 2500, "time": "1:05:00"}]
        }
        context = ContextAssembler(**context_data)
        assert context.athlete.ftp == 300
        assert context.athlete.css == "2:15"
        assert context.athlete.lthr_run == 160
        assert context.athlete.ctl == 7.5
        assert context.athlete.atl == 4.2
        assert context.athlete.tsb == -1.8
        assert context.athlete.hrv_trend == "normal"
        assert context.block.phase == "Build"
        assert context.block.week_in_block == 4
        assert context.block.weeks_to_race == 12
        assert context.block.target_race.date == "2023-05-01"
        assert context.block.target_race.format == "Ironman"
        assert context.block.target_race.priority == "A"
        assert context.yesterday_actual["activity"] == "Run"
        assert context.yesterday_actual["distance"] == 10.5
        assert context.yesterday_actual["time"] == "45:30"
        assert context.retrieved_history[0]["activity"] == "Swim"
        assert context.retrieved_history[0]["distance"] == 2500
        assert context.retrieved_history[0]["time"] == "1:05:00"

    def test_invalid_athlete(self):
        with pytest.raises(ValidationError):
            ContextAssembler(athlete="not a valid AthleteState", block=TrainingBlock(phase="Build", week_in_block=4, weeks_to_race=12, target_race=RaceEvent(date="2023-05-01", format="Ironman", priority="A")), yesterday_actual={"activity": "Run", "distance": 10.5, "time": "45:30"}, retrieved_history=[{"activity": "Swim", "distance": 2500, "time": "1:05:00"}])

    def test_invalid_block(self):
        with pytest.raises(ValidationError):
            ContextAssembler(athlete=AthleteState(ftp=300, css="2:15", lthr_run=160, ctl=7.5, atl=4.2, tsb=-1.8, hrv_trend="normal"), block="not a valid TrainingBlock", yesterday_actual={"activity": "Run", "distance": 10.5, "time": "45:30"}, retrieved_history=[{"activity": "Swim", "distance": 2500, "time": "1:05:00"}])

    def test_invalid_yesterday_actual(self):
        with pytest.raises(ValidationError):
            ContextAssembler(athlete=AthleteState(ftp=300, css="2:15", lthr_run=160, ctl=7.5, atl=4.2, tsb=-1.8, hrv_trend="normal"), block=TrainingBlock(phase="Build", week_in_block=4, weeks_to_race=12, target_race=RaceEvent(date="2023-05-01", format="Ironman", priority="A")), yesterday_actual="not a valid dict", retrieved_history=[{"activity": "Swim", "distance": 2500, "time": "1:05:00"}])

    def test_invalid_retrieved_history(self):
        with pytest.raises(ValidationError):
            ContextAssembler(athlete=AthleteState(ftp=300, css="2:15", lthr_run=160, ctl=7.5, atl=4.2, tsb=-1.8, hrv_trend="normal"), block=TrainingBlock(phase="Build", week_in_block=4, weeks_to_race=12, target_race=RaceEvent(date="2023-05-01", format="Ironman", priority="A")), yesterday_actual={"activity": "Run", "distance": 10.5, "time": "45:30"}, retrieved_history="not a valid list")