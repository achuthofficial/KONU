"""The single output schema shared by every source and pipeline stage."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEGACY_CSV = ROOT / "data" / "raw" / "legacy_listings.csv"
CRAWLED_CSV = ROOT / "data" / "interim" / "crawled_listings.csv"
STATE_DIR = ROOT / "data" / "interim" / "state"
LOG_DIR = ROOT / "logs"
GEOJSON_FILES = [ROOT / "data" / "geo" / "telangana.geojson", ROOT / "data" / "geo" / "andhra-pradesh.geojson"]
FINAL_CSV = ROOT / "data" / "output" / "properties_all_sources.csv"

COLUMNS = [
    "Source", "URL", "YearMonth", "Year", "Month", "Listing_Type", "Property_Type", "Transaction",
    "Price_INR", "Price_Max_INR", "Price_Cr", "PricePerSqft", "Area_Sqft", "Area_Max_Sqft",
    "BHK", "Bathrooms", "Balconies", "Car_Parking", "Floor_Number", "Total_Floors",
    "Property_Age_Years", "Age_Group", "Construction_Status", "Furnishing", "Facing", "Ownership",
    "Overlooking", "Builder", "RERA_ID", "Society", "Locality", "Pincode", "Possible_Pincodes",
    "Latitude", "Longitude", "Full_Address", "Total_Units", "Rating", "Review_Count", "Posted_On",
    "Cement_Price_Rs_per_bag_50kg", "Steel_TMT_Price_Rs_per_tonne",
]
