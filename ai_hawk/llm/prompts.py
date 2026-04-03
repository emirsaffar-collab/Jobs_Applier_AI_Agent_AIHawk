"""Prompt templates used by GPTAnswerer in llm_manager.py."""

# ---------------------------------------------------------------------------
# Summarize
# ---------------------------------------------------------------------------
summarize_prompt_template = """\
Summarize the following job description concisely, highlighting the key
responsibilities, required skills, and qualifications:

{text}
"""

# ---------------------------------------------------------------------------
# Section determination
# ---------------------------------------------------------------------------
determine_section_template = """\
Given the following question from a job application form, determine which
section of the applicant's profile it relates to.

Respond with ONLY one of these exact section names:
Personal information, Self Identification, Legal Authorization,
Work Preferences, Education Details, Experience Details, Projects,
Availability, Salary Expectations, Certifications, Languages, Interests,
Cover letter

Question: {question}
"""

# ---------------------------------------------------------------------------
# Per-section answer templates
# Each template receives {{resume_section}} and {{question}} unless noted.
# ---------------------------------------------------------------------------
personal_information_template = """\
Based on the following personal information, answer the question concisely
and directly. If the information is not available, provide a reasonable
response.

Personal Information:
{resume_section}

Question: {question}
"""

self_identification_template = """\
Based on the following self-identification information, answer the question
concisely and directly.

Self Identification:
{resume_section}

Question: {question}
"""

legal_authorization_template = """\
Based on the following legal authorization information, answer the question
concisely and directly. If not explicitly stated, answer honestly.

Legal Authorization:
{resume_section}

Question: {question}
"""

work_preferences_template = """\
Based on the following work preferences, answer the question concisely
and directly.

Work Preferences:
{resume_section}

Question: {question}
"""

education_details_template = """\
Based on the following education details, answer the question concisely
and directly.

Education Details:
{resume_section}

Question: {question}
"""

experience_details_template = """\
Based on the following experience details, answer the question concisely
and directly.

Experience Details:
{resume_section}

Question: {question}
"""

projects_template = """\
Based on the following projects, answer the question concisely and directly.

Projects:
{resume_section}

Question: {question}
"""

availability_template = """\
Based on the following availability information, answer the question
concisely and directly.

Availability:
{resume_section}

Question: {question}
"""

salary_expectations_template = """\
Based on the following salary expectations, answer the question concisely
and directly.

Salary Expectations:
{resume_section}

Question: {question}
"""

certifications_template = """\
Based on the following certifications, answer the question concisely
and directly.

Certifications:
{resume_section}

Question: {question}
"""

languages_template = """\
Based on the following language proficiencies, answer the question
concisely and directly.

Languages:
{resume_section}

Question: {question}
"""

interests_template = """\
Based on the following interests, answer the question concisely
and directly.

Interests:
{resume_section}

Question: {question}
"""

# Cover letter receives {resume}, {job_description}, {company}
coverletter_template = """\
Write a concise, professional cover letter for the following job application.
Tailor the letter to the company and role, highlighting relevant experience
from the resume. Keep it under 300 words.

Resume:
{resume}

Job Description:
{job_description}

Company: {company}
"""

# ---------------------------------------------------------------------------
# Numeric question
# ---------------------------------------------------------------------------
numeric_question_template = """\
Based on the following resume details, answer the numeric question.
Respond with ONLY a single number (integer). No words, no explanation.

Education:
{resume_educations}

Work Experience:
{resume_jobs}

Projects:
{resume_projects}

Question: {question}
"""

# ---------------------------------------------------------------------------
# Multiple-choice / options
# ---------------------------------------------------------------------------
options_template = """\
Based on the resume and job application profile below, select the BEST
option to answer the question. Respond with ONLY the chosen option text,
nothing else.

Resume:
{resume}

Job Application Profile:
{job_application_profile}

Question: {question}
Options: {options}
"""

# ---------------------------------------------------------------------------
# Resume vs Cover Letter determination
# ---------------------------------------------------------------------------
resume_or_cover_letter_template = """\
Determine if the following phrase is asking for a resume or a cover letter.
Respond with ONLY "resume" or "cover".

Phrase: {phrase}
"""

# ---------------------------------------------------------------------------
# Job suitability scoring
# ---------------------------------------------------------------------------
is_relavant_position_template = """\
Evaluate how well the candidate's resume matches the job description.
Score on a scale of 1-10.

Resume:
{resume}

Job Description:
{job_description}

Respond in this exact format:
Score: <number>
Reasoning: <2-3 sentences explaining the score>
"""
