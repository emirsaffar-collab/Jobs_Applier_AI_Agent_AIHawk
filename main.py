import os
import sys

# Check for web mode early, before importing CLI-specific dependencies
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "web":
    import uvicorn
    import config as cfg
    from src.web.app import app

    print(f"Starting AIHawk web server on {cfg.WEB_HOST}:{cfg.WEB_PORT}")
    uvicorn.run(app, host=cfg.WEB_HOST, port=cfg.WEB_PORT)
    sys.exit(0)

import base64
from pathlib import Path
import traceback
from typing import List, Optional, Tuple, Dict

import click
import inquirer
import yaml
import re
from src.libs.resume_and_cover_builder import ResumeFacade, ResumeGenerator, StyleManager
from src.resume_schemas.job_application_profile import JobApplicationProfile
from src.resume_schemas.resume import Resume
from src.logging import logger
from src.utils.constants import (
    PLAIN_TEXT_RESUME_YAML,
    SECRETS_YAML,
    WORK_PREFERENCES_YAML,
)


class ConfigError(Exception):
    """Custom exception for configuration-related errors."""
    pass


class ConfigValidator:
    """Validates configuration and secrets YAML files."""

    EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    REQUIRED_CONFIG_KEYS = {
        "remote": bool,
        "experience_level": dict,
        "job_types": dict,
        "date": dict,
        "positions": list,
        "locations": list,
        "location_blacklist": list,
        "distance": int,
        "company_blacklist": list,
        "title_blacklist": list,
    }
    EXPERIENCE_LEVELS = [
        "internship",
        "entry",
        "associate",
        "mid_senior_level",
        "director",
        "executive",
    ]
    JOB_TYPES = [
        "full_time",
        "contract",
        "part_time",
        "temporary",
        "internship",
        "other",
        "volunteer",
    ]
    DATE_FILTERS = ["all_time", "month", "week", "24_hours"]
    APPROVED_DISTANCES = {0, 5, 10, 25, 50, 100}

    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate the format of an email address."""
        return bool(ConfigValidator.EMAIL_REGEX.match(email))

    @staticmethod
    def load_yaml(yaml_path: Path) -> dict:
        """Load and parse a YAML file."""
        try:
            with open(yaml_path, "r") as stream:
                return yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            raise ConfigError(f"Error reading YAML file {yaml_path}: {exc}")
        except FileNotFoundError:
            raise ConfigError(f"YAML file not found: {yaml_path}")

    @classmethod
    def validate_config(cls, config_yaml_path: Path) -> dict:
        """Validate the main configuration YAML file."""
        parameters = cls.load_yaml(config_yaml_path)
        # Check for required keys and their types
        for key, expected_type in cls.REQUIRED_CONFIG_KEYS.items():
            if key not in parameters:
                if key in ["company_blacklist", "title_blacklist", "location_blacklist"]:
                    parameters[key] = []
                    logger.warning(
                        f"'{key}' not found in {config_yaml_path} — defaulting to empty list (no filtering)."
                    )
                else:
                    raise ConfigError(f"Missing required key '{key}' in {config_yaml_path}")
            elif not isinstance(parameters[key], expected_type):
                if key in ["company_blacklist", "title_blacklist", "location_blacklist"] and parameters[key] is None:
                    parameters[key] = []
                    logger.warning(
                        f"'{key}' is null in {config_yaml_path} — defaulting to empty list (no filtering)."
                    )
                else:
                    raise ConfigError(
                        f"Invalid type for key '{key}' in {config_yaml_path}. Expected {expected_type.__name__}."
                    )
        cls._validate_experience_levels(parameters["experience_level"], config_yaml_path)
        cls._validate_job_types(parameters["job_types"], config_yaml_path)
        cls._validate_date_filters(parameters["date"], config_yaml_path)
        cls._validate_list_of_strings(parameters, ["positions", "locations"], config_yaml_path)
        cls._validate_distance(parameters["distance"], config_yaml_path)
        cls._validate_blacklists(parameters, config_yaml_path)

        # Apply optional tuning parameters from YAML to config (env vars take precedence)
        import config as cfg
        if "min_suitability_score" in parameters and not os.environ.get("JOB_SUITABILITY_SCORE"):
            cfg.JOB_SUITABILITY_SCORE = int(parameters["min_suitability_score"])
        if "max_applications" in parameters and not os.environ.get("JOB_MAX_APPLICATIONS"):
            cfg.JOB_MAX_APPLICATIONS = int(parameters["max_applications"])
        if "wait_between_applications" in parameters and not os.environ.get("MINIMUM_WAIT_TIME_IN_SECONDS"):
            cfg.MINIMUM_WAIT_TIME_IN_SECONDS = int(parameters["wait_between_applications"])

        return parameters

    @classmethod
    def _validate_experience_levels(cls, experience_levels: dict, config_path: Path):
        """Ensure experience levels are booleans."""
        for level in cls.EXPERIENCE_LEVELS:
            if not isinstance(experience_levels.get(level), bool):
                raise ConfigError(
                    f"Experience level '{level}' must be a boolean in {config_path}"
                )

    @classmethod
    def _validate_job_types(cls, job_types: dict, config_path: Path):
        """Ensure job types are booleans."""
        for job_type in cls.JOB_TYPES:
            if not isinstance(job_types.get(job_type), bool):
                raise ConfigError(
                    f"Job type '{job_type}' must be a boolean in {config_path}"
                )

    @classmethod
    def _validate_date_filters(cls, date_filters: dict, config_path: Path):
        """Ensure date filters are booleans."""
        for date_filter in cls.DATE_FILTERS:
            if not isinstance(date_filters.get(date_filter), bool):
                raise ConfigError(
                    f"Date filter '{date_filter}' must be a boolean in {config_path}"
                )

    @classmethod
    def _validate_list_of_strings(cls, parameters: dict, keys: list, config_path: Path):
        """Ensure specified keys are lists of strings."""
        for key in keys:
            if not all(isinstance(item, str) for item in parameters[key]):
                raise ConfigError(
                    f"'{key}' must be a list of strings in {config_path}"
                )

    @classmethod
    def _validate_distance(cls, distance: int, config_path: Path):
        """Validate the distance value."""
        if distance not in cls.APPROVED_DISTANCES:
            raise ConfigError(
                f"Invalid distance value '{distance}' in {config_path}. "
                f"Must be one of: {sorted(cls.APPROVED_DISTANCES)} "
                f"(these match LinkedIn's supported search radius values in miles)."
            )

    @classmethod
    def _validate_blacklists(cls, parameters: dict, config_path: Path):
        """Ensure blacklists are lists."""
        for blacklist in ["company_blacklist", "title_blacklist", "location_blacklist"]:
            if not isinstance(parameters.get(blacklist), list):
                raise ConfigError(
                    f"'{blacklist}' must be a list in {config_path}"
                )

    @staticmethod
    def validate_secrets(secrets_yaml_path: Path) -> str:
        """Validate the secrets YAML file and retrieve the LLM API key.

        Falls back to the LLM_API_KEY environment variable when the YAML
        file is missing or the key is empty, allowing Railway/Docker
        deployments to configure secrets via env vars alone.
        """
        import config as cfg
        from src.utils.llm_providers import get_provider_info

        # Prefer env var when set (Railway / Docker deployments)
        if cfg.LLM_API_KEY:
            return cfg.LLM_API_KEY

        provider = get_provider_info(cfg.LLM_MODEL_TYPE)
        key_hint = (
            f"\n  Get your {provider['name']} API key at: {provider['dashboard_url']}"
            if provider.get("dashboard_url")
            else ""
        )

        # Fall back to secrets.yaml
        try:
            secrets = ConfigValidator.load_yaml(secrets_yaml_path)
        except ConfigError:
            raise ConfigError(
                f"LLM API key not found.{key_hint}\n"
                f"  Then either:\n"
                f"    - Set the LLM_API_KEY environment variable, or\n"
                f"    - Add 'llm_api_key: <your-key>' to {secrets_yaml_path}"
            )

        api_key = secrets.get("llm_api_key", "")
        if not api_key:
            raise ConfigError(
                f"LLM API key is empty.{key_hint}\n"
                f"  Then either:\n"
                f"    - Set the LLM_API_KEY environment variable, or\n"
                f"    - Add 'llm_api_key: <your-key>' to {secrets_yaml_path}"
            )

        return api_key


class FileManager:
    """Handles file system operations and validations."""

    REQUIRED_FILES = [SECRETS_YAML, WORK_PREFERENCES_YAML, PLAIN_TEXT_RESUME_YAML]

    @staticmethod
    def validate_data_folder(app_data_folder: Path) -> Tuple[Path, Path, Path, Path]:
        """Validate the existence of the data folder and required files."""
        if not app_data_folder.is_dir():
            raise FileNotFoundError(f"Data folder not found: {app_data_folder}")

        # Auto-create missing files from data_folder_example/ templates
        example_folder = Path("data_folder_example")
        missing_files = [file for file in FileManager.REQUIRED_FILES if not (app_data_folder / file).exists()]
        created_from_template = []
        if missing_files and example_folder.is_dir():
            import shutil
            still_missing = []
            for file in missing_files:
                src = example_folder / file
                if src.exists():
                    shutil.copy2(src, app_data_folder / file)
                    created_from_template.append(file)
                    logger.warning(f"Created {app_data_folder / file} from template — please edit with your details.")
                else:
                    still_missing.append(file)
            missing_files = still_missing

        # First-run banner when template files were just created
        if created_from_template:
            logger.info(
                "\n"
                "====================================================\n"
                "  AIHawk Jobs Applier — First-Run Setup\n"
                "====================================================\n"
                "  Template files were created in data_folder/.\n"
                "  Complete these steps before running again:\n"
                "\n"
                "  1. Add your LLM API key:\n"
                "     → Edit data_folder/secrets.yaml, or\n"
                "     → Set the LLM_API_KEY environment variable\n"
                "\n"
                "  2. Add platform credentials (LinkedIn, etc.):\n"
                "     → Edit data_folder/credentials.yaml, or\n"
                "     → Set LINKEDIN_EMAIL / LINKEDIN_PASSWORD env vars\n"
                "\n"
                "  3. Customize your job search preferences:\n"
                "     → Edit data_folder/work_preferences.yaml\n"
                "\n"
                "  For the web UI (guided setup), run:\n"
                "     python main.py web\n"
                "===================================================="
            )

        if missing_files:
            raise FileNotFoundError(f"Missing files in data folder: {', '.join(missing_files)}")

        output_folder = app_data_folder / "output"
        output_folder.mkdir(exist_ok=True)

        return (
            app_data_folder / SECRETS_YAML,
            app_data_folder / WORK_PREFERENCES_YAML,
            app_data_folder / PLAIN_TEXT_RESUME_YAML,
            output_folder,
        )

    @staticmethod
    def get_uploads(plain_text_resume_file: Path) -> Dict[str, Path]:
        """Convert resume file paths to a dictionary."""
        if not plain_text_resume_file.exists():
            raise FileNotFoundError(f"Plain text resume file not found: {plain_text_resume_file}")

        uploads = {"plainTextResume": plain_text_resume_file}

        return uploads


def _setup_facade(parameters: dict, llm_api_key: str, job_url: Optional[str] = None) -> Tuple[ResumeFacade, StyleManager]:
    """Shared setup for all document generation functions."""
    with open(parameters["uploads"]["plainTextResume"], "r", encoding="utf-8") as file:
        plain_text_resume = file.read()

    style_manager = StyleManager()
    available_styles = style_manager.get_styles()

    if available_styles:
        choices = style_manager.format_choices(available_styles)
        questions = [
            inquirer.List("style", message="Select a style for the resume:", choices=choices)
        ]
        style_answer = inquirer.prompt(questions)
        if style_answer and "style" in style_answer:
            selected_choice = style_answer["style"]
            for style_name, (file_name, author_link) in available_styles.items():
                if selected_choice.startswith(style_name):
                    style_manager.set_selected_style(style_name)
                    logger.info(f"Selected style: {style_name}")
                    break
        else:
            logger.warning("No style selected. Proceeding with default style.")
    else:
        logger.warning("No styles available. Proceeding without style selection.")

    resume_generator = ResumeGenerator()
    resume_object = Resume(plain_text_resume)
    try:
        from src.utils.chrome_utils import init_browser
        driver = init_browser()
    except (ImportError, Exception) as exc:
        logger.warning("Selenium/Chrome not available for PDF generation: {}. "
                       "Use 'python main.py web' for a full-featured experience.", exc)
        driver = None
    resume_generator.set_resume_object(resume_object)

    resume_facade = ResumeFacade(
        api_key=llm_api_key,
        style_manager=style_manager,
        resume_generator=resume_generator,
        resume_object=resume_object,
        output_path=Path("data_folder/output"),
    )
    resume_facade.set_driver(driver)

    if job_url:
        resume_facade.link_to_job(job_url)

    return resume_facade, style_manager


def _save_pdf(result_base64: str, output_dir: Path, filename: str) -> None:
    """Decode a base64 PDF and save it to disk."""
    pdf_data = base64.b64decode(result_base64)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    with open(output_path, "wb") as file:
        file.write(pdf_data)
    logger.info(f"Document saved at: {output_path}")


def _prompt_job_url() -> str:
    """Ask the user for a job description URL."""
    questions = [inquirer.Text('job_url', message="Please enter the URL of the job description:")]
    answers = inquirer.prompt(questions)
    if answers is None:
        return ""
    return answers.get('job_url', '')


def create_cover_letter(parameters: dict, llm_api_key: str):
    """Generate a tailored cover letter."""
    driver = None
    try:
        logger.info("Generating a cover letter based on provided parameters.")
        job_url = _prompt_job_url()
        if not job_url:
            logger.warning("No job URL provided. Aborting.")
            return
        resume_facade, _ = _setup_facade(parameters, llm_api_key, job_url)
        driver = getattr(resume_facade, 'driver', None)
        result_base64, suggested_name = resume_facade.create_cover_letter()

        output_dir = Path(parameters["outputFileDirectory"]) / suggested_name
        _save_pdf(result_base64, output_dir, "cover_letter_tailored.pdf")
    except Exception as e:
        logger.exception(f"An error occurred while creating the cover letter: {e}")
        if driver:
            try:
                driver.quit()
            except (OSError, WebDriverException):
                pass
        raise


def create_resume_pdf_job_tailored(parameters: dict, llm_api_key: str):
    """Generate a resume tailored to a job description."""
    driver = None
    try:
        logger.info("Generating a tailored resume based on provided parameters.")
        job_url = _prompt_job_url()
        if not job_url:
            logger.warning("No job URL provided. Aborting.")
            return
        resume_facade, _ = _setup_facade(parameters, llm_api_key, job_url)
        driver = getattr(resume_facade, 'driver', None)
        result_base64, suggested_name = resume_facade.create_resume_pdf_job_tailored()

        output_dir = Path(parameters["outputFileDirectory"]) / suggested_name
        _save_pdf(result_base64, output_dir, "resume_tailored.pdf")
    except Exception as e:
        logger.exception(f"An error occurred while creating the tailored resume: {e}")
        if driver:
            try:
                driver.quit()
            except (OSError, WebDriverException):
                pass
        raise


def create_resume_pdf(parameters: dict, llm_api_key: str):
    """Generate a base resume PDF."""
    driver = None
    try:
        logger.info("Generating a base resume.")
        resume_facade, _ = _setup_facade(parameters, llm_api_key)
        driver = getattr(resume_facade, 'driver', None)
        result_base64 = resume_facade.create_resume_pdf()

        output_dir = Path(parameters["outputFileDirectory"])
        _save_pdf(result_base64, output_dir, "resume_base.pdf")
    except Exception as e:
        logger.exception(f"An error occurred while creating the resume: {e}")
        if driver:
            try:
                driver.quit()
            except (OSError, WebDriverException):
                pass
        raise

        
def handle_inquiries(selected_actions: List[str], parameters: dict, llm_api_key: str):
    """
    Decide which function to call based on the selected user actions.

    :param selected_actions: List of actions selected by the user.
    :param parameters: Configuration parameters dictionary.
    :param llm_api_key: API key for the language model.
    """
    try:
        if selected_actions:
            if "Generate Resume" == selected_actions:
                logger.info("Crafting a standout professional resume...")
                create_resume_pdf(parameters, llm_api_key)
                
            if "Generate Resume Tailored for Job Description" == selected_actions:
                logger.info("Customizing your resume to enhance your job application...")
                create_resume_pdf_job_tailored(parameters, llm_api_key)
                
            if "Generate Tailored Cover Letter for Job Description" == selected_actions:
                logger.info("Designing a personalized cover letter to enhance your job application...")
                create_cover_letter(parameters, llm_api_key)

        else:
            logger.warning("No actions selected. Nothing to execute.")
    except Exception as e:
        logger.exception(f"An error occurred while handling inquiries: {e}")
        raise

def prompt_user_action() -> str:
    """
    Use inquirer to ask the user which action they want to perform.

    :return: Selected action.
    """
    try:
        questions = [
            inquirer.List(
                'action',
                message="Select the action you want to perform:",
                choices=[
                    "Generate Resume",
                    "Generate Resume Tailored for Job Description",
                    "Generate Tailored Cover Letter for Job Description",
                ],
            ),
        ]
        answer = inquirer.prompt(questions)
        if answer is None:
            print("No answer provided. The user may have interrupted.")
            return ""
        return answer.get('action', "")
    except Exception as e:
        print(f"An error occurred: {e}")
        return ""


def main():
    """Main entry point for the AIHawk Job Application Bot."""
    try:
        # Define and validate the data folder
        data_folder = Path("data_folder")
        secrets_file, config_file, plain_text_resume_file, output_folder = FileManager.validate_data_folder(data_folder)

        # Validate configuration and secrets
        config = ConfigValidator.validate_config(config_file)
        llm_api_key = ConfigValidator.validate_secrets(secrets_file)

        # Prepare parameters
        config["uploads"] = FileManager.get_uploads(plain_text_resume_file)
        config["outputFileDirectory"] = output_folder

        # Interactive prompt for user to select actions
        selected_actions = prompt_user_action()

        # Handle selected actions and execute them
        handle_inquiries(selected_actions, config, llm_api_key)

    except ConfigError as ce:
        logger.error(f"Configuration error: {ce}")
        logger.error(
            "Refer to the configuration guide for troubleshooting: "
            "https://github.com/feder-cr/Auto_Jobs_Applier_AIHawk?tab=readme-ov-file#configuration"
        )
    except FileNotFoundError as fnf:
        logger.error(f"File not found: {fnf}")
        logger.error("Ensure all required files are present in the data folder.")
    except RuntimeError as re:
        logger.error(f"Runtime error: {re}")
        logger.debug(traceback.format_exc())
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
