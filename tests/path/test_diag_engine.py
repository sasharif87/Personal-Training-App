import pytest
from unittest.mock import patch, MagicMock
from tmp.diag_engine import Engine

class TestEngine:
    
    @pytest.mark.parametrize("url", ["http://192.168.50.46:11434", "https://example.com"])
    def test_engine_initialization(self, url):
        with patch('tmp.diag_engine.Engine', autospec=True) as mock_engine:
            engine = Engine(url=url)
            assert isinstance(engine, Engine), "Engine instance should be created successfully"
            mock_engine.assert_called_once_with(url=url)
    
    def test_import_engine(self):
        with patch('sys.stdout', new_callable=MagicMock) as mock_stdout:
            import tmp.diag_engine  # Importing the module to trigger the try-except block
            assert "SUCCESS: Imported Engine" in mock_stdout.getvalue(), "Import should succeed"
    
    @pytest.mark.parametrize("url", [None, "", "invalid_url"])
    def test_engine_initialization_with_invalid_urls(self, url):
        with pytest.raises(ValueError) as excinfo:
            Engine(url=url)
        assert str(excinfo.value) == "Invalid URL", "Engine should raise ValueError for invalid URLs"
    
    def test_engine_test_method(self):
        with patch('tmp.diag_engine.Engine', autospec=True) as mock_engine:
            mock_engine_instance = mock_engine.return_value
            mock_engine_instance.test.return_value = (True, ["model1", "model2"], "Test successful")
            
            engine = Engine(url="http://192.168.50.46:11434")
            ok, models, msg = engine.test()
            
            assert ok is True, "The test method should return True on success"
            assert models == ["model1", "model2"], "Available models should match the expected list"
            assert msg == "Test successful", "Message should be 'Test successful'"
    
    def test_engine_print_model_map(self):
        with patch('tmp.diag_engine.Engine', autospec=True) as mock_engine:
            mock_engine_instance = mock_engine.return_value
            mock_engine_instance.print_model_map.return_value = None
            
            engine = Engine(url="http://192.168.50.46:11434")
            with patch('sys.stdout', new_callable=MagicMock) as mock_stdout:
                engine.print_model_map()
                assert "Model Map:" in mock_stdout.getvalue(), "The model map should be printed"