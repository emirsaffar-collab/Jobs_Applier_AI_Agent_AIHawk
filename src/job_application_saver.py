"""Save job application details, resume, and cover letter to disk."""
from src.logging import logger
import os
import json
import shutil
from dataclasses import asdict
from typing import Any

import config as cfg
from src.job import Job

# Base directory where all applications will be saved
BASE_DIR = cfg.JOB_APPLICATIONS_DIR


class ApplicationSaver:

    def __init__(self, job_application: Any):
        self.job_application = job_application
        self.job_application_files_path = None

    def create_application_directory(self):
        job = self.job_application.job

        dir_name = f"{getattr(job, 'id', 'unknown')} - {job.company} {getattr(job, 'title', job.role)}"
        dir_path = os.path.join(BASE_DIR, dir_name)

        os.makedirs(dir_path, exist_ok=True)
        self.job_application_files_path = dir_path
        return dir_path

    def save_application_details(self):
        if self.job_application_files_path is None:
            raise ValueError(
                "Job application file path is not set. Please create the application directory first."
            )

        json_file_path = os.path.join(
            self.job_application_files_path, "job_application.json"
        )
        with open(json_file_path, "w") as json_file:
            json.dump(self.job_application.application, json_file, indent=4)

    def save_file(self, dir_path, file_path, new_filename):
        if dir_path is None:
            raise ValueError("dir path cannot be None")

        destination = os.path.join(dir_path, new_filename)
        shutil.copy(file_path, destination)

    def save_job_description(self):
        if self.job_application_files_path is None:
            raise ValueError(
                "Job application file path is not set. Please create the application directory first."
            )

        job: Job = self.job_application.job

        json_file_path = os.path.join(
            self.job_application_files_path, "job_description.json"
        )
        with open(json_file_path, "w") as json_file:
            json.dump(asdict(job), json_file, indent=4)

    @staticmethod
    def save(job_application: Any):
        saver = ApplicationSaver(job_application)
        saver.create_application_directory()
        saver.save_application_details()
        saver.save_job_description()
        if getattr(job_application, 'resume_path', None):
            saver.save_file(
                saver.job_application_files_path,
                job_application.job.resume_path,
                "resume.pdf",
            )
        logger.debug(f"Saving cover letter to path: {getattr(job_application, 'cover_letter_path', '')}")
        if getattr(job_application, 'cover_letter_path', None):
            saver.save_file(
                saver.job_application_files_path,
                job_application.job.cover_letter_path,
                "cover_letter.pdf"
            )
