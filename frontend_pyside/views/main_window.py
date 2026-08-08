from PySide6.QtWidgets import QMainWindow, QTabWidget

from frontend_pyside.views.dataset_page import DatasetPage
from frontend_pyside.views.simulation_page import SimulationPage
from frontend_pyside.views.training_page import TrainingPage
from frontend_pyside.views.verification_page import VerificationPage


class MainWindow(QMainWindow):
    def __init__(self, api_client):
        super().__init__()
        self.setWindowTitle("Optical Simulation and ML Platform")

        self.simulation_page = SimulationPage(api_client)
        self.dataset_page = DatasetPage(api_client)
        self.training_page = TrainingPage(api_client)
        self.verification_page = VerificationPage(api_client)

        self.dataset_page.dataset_ready.connect(self.training_page.set_dataset_id)
        self.training_page.model_ready.connect(self.verification_page.set_model_id)

        tabs = QTabWidget()
        tabs.addTab(self.simulation_page, "Simulation")
        tabs.addTab(self.dataset_page, "Dataset")
        tabs.addTab(self.training_page, "Training")
        tabs.addTab(self.verification_page, "Prediction")
        self.setCentralWidget(tabs)
