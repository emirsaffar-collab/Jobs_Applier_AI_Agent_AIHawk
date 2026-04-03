"""Tests for Resume Pydantic schema and YAML parsing."""
import pytest
from src.resume_schemas.resume import (
    Resume, PersonalInformation, EducationDetails, ExperienceDetails,
    Project, Achievement, Certifications, Language, Availability,
    SalaryExpectations, SelfIdentification, LegalAuthorization,
)


MINIMAL_YAML = """\
personal_information:
  name: "John"
  surname: "Doe"
  email: "john@example.com"
"""

FULL_YAML = """\
personal_information:
  name: "Jane"
  surname: "Smith"
  date_of_birth: "1990-01-01"
  country: "US"
  city: "New York"
  address: "123 Main St"
  phone_prefix: "+1"
  phone: "5551234567"
  email: "jane@example.com"

education_details:
  - education_level: "Bachelor"
    institution: "MIT"
    field_of_study: "Computer Science"
    final_evaluation_grade: "3.8"
    start_date: "2008"
    year_of_completion: 2012
    exam:
      Math: "A"
      Physics: "B+"

experience_details:
  - position: "Engineer"
    company: "Acme"
    employment_period: "01/2015 - 12/2020"
    location: "NYC"
    industry: "Tech"
    key_responsibilities:
      - responsibility: "Built stuff"
    skills_acquired:
      - "Python"
      - "Docker"

projects:
  - name: "My Project"
    description: "A cool project"

achievements:
  - name: "Award"
    description: "Won an award"

certifications:
  - name: "AWS"
    description: "Solutions Architect"

languages:
  - language: "English"
    proficiency: "Native"

interests:
  - "Hiking"
  - "Reading"

availability:
  notice_period: "2 weeks"

salary_expectations:
  salary_range_usd: "100000-150000"

self_identification:
  gender: "Male"
  pronouns: "he/him"

legal_authorization:
  us_work_authorization: "Yes"
"""


class TestPersonalInformation:
    def test_all_fields_optional(self):
        pi = PersonalInformation()
        assert pi.name is None
        assert pi.email is None

    def test_with_data(self):
        pi = PersonalInformation(name="John", email="john@example.com")
        assert pi.name == "John"


class TestResume:
    def test_minimal_yaml(self):
        resume = Resume(MINIMAL_YAML)
        assert resume.personal_information.name == "John"
        assert resume.personal_information.surname == "Doe"
        assert resume.education_details is None

    def test_full_yaml(self):
        resume = Resume(FULL_YAML)
        assert resume.personal_information.name == "Jane"
        assert len(resume.education_details) == 1
        assert len(resume.experience_details) == 1
        assert resume.education_details[0].institution == "MIT"
        assert resume.experience_details[0].company == "Acme"
        assert len(resume.projects) == 1
        assert len(resume.languages) == 1
        assert resume.availability.notice_period == "2 weeks"

    def test_empty_yaml(self):
        resume = Resume("---\n")
        assert resume.personal_information is None

    def test_exam_normalization_dict_to_list(self):
        yaml_str = """\
education_details:
  - education_level: "BS"
    institution: "MIT"
    exam:
      Math: "A"
      Physics: "B"
"""
        resume = Resume(yaml_str)
        exams = resume.education_details[0].exam
        assert isinstance(exams, list)
        assert len(exams) == 2

    def test_exam_normalization_already_list(self):
        yaml_str = """\
education_details:
  - education_level: "BS"
    institution: "MIT"
    exam:
      - Math: "A"
"""
        resume = Resume(yaml_str)
        exams = resume.education_details[0].exam
        assert isinstance(exams, list)

    def test_missing_optional_sections(self):
        yaml_str = """\
personal_information:
  name: "Test"
"""
        resume = Resume(yaml_str)
        assert resume.projects is None
        assert resume.certifications is None
        assert resume.languages is None

    def test_invalid_yaml_raises(self):
        with pytest.raises(ValueError, match="Error parsing YAML"):
            Resume("{{invalid yaml}}: [")

    def test_partial_personal_info(self):
        yaml_str = """\
personal_information:
  name: "Only Name"
"""
        resume = Resume(yaml_str)
        assert resume.personal_information.name == "Only Name"
        assert resume.personal_information.surname is None
        assert resume.personal_information.phone is None
