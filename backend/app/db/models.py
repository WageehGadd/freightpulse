from sqlalchemy import JSON, Column, Date, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class CarrierAdvisory(Base):
    __tablename__ = "carrier_advisories"

    id = Column(Integer, primary_key=True, index=True)
    carrier = Column(String, nullable=False)
    title = Column(String, nullable=False)
    raw_text = Column(Text, nullable=False)

    summary = Column(Text, nullable=True)
    advisory_type = Column(String, nullable=True)
    affected_lanes = Column(JSON, nullable=True)
    effective_date = Column(Date, nullable=True)
    impact_severity = Column(String, nullable=True)
