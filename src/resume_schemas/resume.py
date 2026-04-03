from typing import List, Dict, Any, Optional, Union
import yaml
from pydantic import BaseModel, EmailStr, HttpUrl, Field


class PersonalInformation(BaseModel):
    name: Optional[str] = None
    surname: Optional[str] = None
    date_of_birth: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    zip_code: Optional[str] = Field(None, min_length=5, max_length=10)
    phone_prefix: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    github: Optional[HttpUrl] = None
    linkedin: Optional[HttpUrl] = None


class EducationDetails(BaseModel):
    education_level: Optional[str] = None
    institution: Optional[str] = None
    field_of_study: Optional[str] = None
    final_evaluation_grade: Optional[str] = None
    start_date: Optional[str] = None
    year_of_completion: Optional[int] = None
    exam: Optional[Union[List[Dict[str, str]], Dict[str, str]]] = None


class ExperienceDetails(BaseModel):
    position: Optional[str] = None
    company: Optional[str] = None
    employment_period: Optional[str] = None
    location: Optional[str] = None
    industry: Optional[str] = None
    key_responsibilities: Optional[List[Dict[str, str]]] = None
    skills_acquired: Optional[List[str]] = None


class Project(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    link: Optional[HttpUrl] = None


class Achievement(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class Certifications(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class Language(BaseModel):
    language: Optional[str] = None
    proficiency: Optional[str] = None


class Availability(BaseModel):
    notice_period: Optional[str] = None


class SalaryExpectations(BaseModel):
    salary_range_usd: Optional[str] = None


class SelfIdentification(BaseModel):
    gender: Optional[str] = None
    pronouns: Optional[str] = None
    veteran: Optional[str] = None
    disability: Optional[str] = None
    ethnicity: Optional[str] = None


class LegalAuthorization(BaseModel):
    eu_work_authorization: Optional[str] = None
    us_work_authorization: Optional[str] = None
    requires_us_visa: Optional[str] = None
    requires_us_sponsorship: Optional[str] = None
    requires_eu_visa: Optional[str] = None
    legally_allowed_to_work_in_eu: Optional[str] = None
    legally_allowed_to_work_in_us: Optional[str] = None
    requires_eu_sponsorship: Optional[str] = None
    canada_work_authorization: Optional[str] = None
    requires_canada_visa: Optional[str] = None
    legally_allowed_to_work_in_canada: Optional[str] = None
    requires_canada_sponsorship: Optional[str] = None
    uk_work_authorization: Optional[str] = None
    requires_uk_visa: Optional[str] = None
    legally_allowed_to_work_in_uk: Optional[str] = None
    requires_uk_sponsorship: Optional[str] = None


class WorkPreferences(BaseModel):
    remote_work: Optional[str] = None
    in_person_work: Optional[str] = None
    open_to_relocation: Optional[str] = None
    willing_to_complete_assessments: Optional[str] = None
    willing_to_undergo_drug_tests: Optional[str] = None
    willing_to_undergo_background_checks: Optional[str] = None


class Resume(BaseModel):
    personal_information: Optional[PersonalInformation] = None
    education_details: Optional[List[EducationDetails]] = None
    experience_details: Optional[List[ExperienceDetails]] = None
    projects: Optional[List[Project]] = None
    achievements: Optional[List[Achievement]] = None
    certifications: Optional[List[Certifications]] = None
    languages: Optional[List[Language]] = None
    interests: Optional[List[str]] = None
    availability: Optional[Availability] = None
    salary_expectations: Optional[SalaryExpectations] = None
    self_identification: Optional[SelfIdentification] = None
    legal_authorization: Optional[LegalAuthorization] = None
    work_preferences: Optional[WorkPreferences] = None

    @staticmethod
    def normalize_exam_format(exam):
        if isinstance(exam, dict):
            return [{k: v} for k, v in exam.items()]
        return exam

    def __init__(self, yaml_str: str):
        try:
            data = yaml.safe_load(yaml_str)
            if not isinstance(data, dict):
                data = {}

            if 'education_details' in data and data['education_details']:
                for ed in data['education_details']:
                    if isinstance(ed, dict) and 'exam' in ed:
                        ed['exam'] = Resume.normalize_exam_format(ed['exam'])

            super().__init__(**data)
        except yaml.YAMLError as e:
            raise ValueError("Error parsing YAML file.") from e
        except Exception as e:
            raise Exception(f"Unexpected error while parsing YAML: {e}") from e
