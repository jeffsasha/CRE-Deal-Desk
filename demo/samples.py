"""Text of the fictional SAMPLE documents used in demo mode and tests.

Every name, address and amount is invented and marked as a sample. None of this
reflects SKW transaction history.
"""
from datetime import timedelta


def fmt(d):
    return f"{d:%B} {d.day}, {d.year}"


BANNER = "SAMPLE DOCUMENT - FICTIONAL - FOR DEMONSTRATION ONLY"


def ambiguous_contract(signed_seller, signed_buyer):
    """Scanned purchase contract whose effective date is defined by an event."""
    return [
        [
            BANNER,
            "",
            "COMMERCIAL PURCHASE AND SALE AGREEMENT",
            "",
            "This Commercial Purchase and Sale Agreement is made by and between Sample Westpark Seller LP (\"Seller\") "
            "and Sample Buyer Holdings LLC (\"Buyer\") for the real property commonly known as 8800 Sample Westpark "
            "Drive, Houston, Texas, as more particularly described in Exhibit A (the \"Property\").",
            "",
            "1. Purchase Price. The Purchase Price is $4,200,000.00, payable in cash at Closing.",
            "",
            "2. Earnest Money. Within three (3) business days after the Effective Date, Buyer shall deposit "
            "earnest money in the amount of $100,000.00 with Example Title Company (Demo), as escrow agent.",
            "",
            "3. Feasibility Period. Buyer shall have a feasibility period of sixty (60) days after the Effective "
            "Date to inspect the Property. Buyer may terminate this Agreement by written notice to Seller delivered "
            "before the end of the Feasibility Period.",
        ],
        [
            BANNER,
            "",
            "4. Title Commitment. Seller shall cause the Title Company to deliver a title commitment to Buyer within "
            "fifteen (15) days after the Effective Date.",
            "",
            "5. Survey. Seller shall deliver its existing survey of the Property within fifteen (15) days after the "
            "Effective Date.",
            "",
            "6. Objections. Buyer may object to any matter shown in the commitment or the survey within ten (10) "
            "days after the later of receipt of the commitment and the survey.",
            "",
            "7. Closing. Closing shall occur on or before the thirtieth (30th) day after the expiration of the "
            "Feasibility Period.",
            "",
            "8. Effective Date. The \"Effective Date\" means the date on which the Title Company acknowledges "
            "receipt of a fully executed copy of this Agreement and the Earnest Money.",
        ],
        [
            BANNER,
            "",
            "SELLER: Sample Westpark Seller LP",
            "By: /s/ Pat Example",
            f"Date: {fmt(signed_seller)}",
            "",
            "BUYER: Sample Buyer Holdings LLC",
            "By: /s/ Lee Sample",
            f"Date: {fmt(signed_buyer)}",
            "",
            "TITLE COMPANY RECEIPT: ______________________  Date: ____________",
        ],
    ]


def executed_contract(effective, closing):
    return [
        [
            BANNER,
            "",
            "COMMERCIAL CONTRACT OF SALE",
            "",
            "This contract is made by and between Sample Gessner Owner LLC (\"Seller\") and Sample Logistics "
            "Partners LLC (\"Buyer\") for the property commonly known as 4400 Sample Gessner Road, Houston, Texas.",
            "",
            f"1. Effective Date. The Effective Date of this contract is {fmt(effective)}.",
            "",
            "2. Purchase Price. The Purchase Price is $2,850,000.00.",
            "",
            "3. Earnest Money. Buyer shall deposit the earnest money in the amount of $75,000.00 with Example Title "
            "Company (Demo) within three (3) days after the Effective Date.",
            "",
            "4. Feasibility Period. The feasibility period shall be forty-five (45) days after the Effective Date.",
        ],
        [
            BANNER,
            "",
            "5. Title Commitment. Seller shall furnish a title commitment within twenty (20) days after the "
            "Effective Date.",
            "",
            "6. Survey. Seller shall deliver a survey within twenty (20) days after the Effective Date.",
            "",
            "7. Objections. Buyer may deliver objections within ten (10) days after the later of receipt of the "
            "title commitment and the survey.",
            "",
            f"8. Closing. Closing shall take place on or before {fmt(closing)}.",
            "",
            "SELLER: Sample Gessner Owner LLC   By: /s/ Jordan Example",
            "BUYER: Sample Logistics Partners LLC   By: /s/ Morgan Sample",
        ],
    ]


def first_amendment(new_closing):
    return [[
        BANNER,
        "",
        "FIRST AMENDMENT TO COMMERCIAL CONTRACT OF SALE",
        "",
        "Seller and Buyer amend the contract for 4400 Sample Gessner Road as follows:",
        "",
        "1. The Feasibility Period is hereby extended to a total of sixty (60) days after the Effective Date.",
        "",
        f"2. The Closing Date is hereby extended to {fmt(new_closing)}.",
        "",
        "All other terms remain unchanged.",
        "",
        "SELLER: Sample Gessner Owner LLC   By: /s/ Jordan Example",
        "BUYER: Sample Logistics Partners LLC   By: /s/ Morgan Sample",
    ]]


def unsigned_extension(new_closing):
    return [[
        BANNER,
        "",
        "SECOND AMENDMENT (EXTENSION) TO COMMERCIAL CONTRACT OF SALE",
        "",
        f"1. The Closing Date is hereby extended to {fmt(new_closing)}.",
        "",
        "2. In consideration of this extension, Buyer shall deposit an additional deposit of $25,000.00.",
        "",
        "SELLER: Sample Gessner Owner LLC   By: ______________________",
        "BUYER: Sample Logistics Partners LLC   By: ______________________",
    ]]


def blank_scan():
    """An unreadable 'scan' used to demonstrate graceful extraction failure."""
    return [[""]]


def historical_csv(today):
    y = today.year - 2
    rows = [
        "Deal name,Type,Status,Property,Address,City,Property type,Client,Side,Closing date,Closing price,Commission,Commission received,Received date,Title company,Notes",
        f"SAMPLE Historical sale - 77 Example Blvd,Sale,Closed,Sample Example Blvd Building,77 Example Blvd,Houston,Office,Sample Historical Client LLC,Seller,{y}-05-14,\"$1,975,000.00\",,,,Example Title Company (Demo),Price verified from closing statement; commission not in source file",
        f"SAMPLE Historical lease - Suite 140,Lease,Leased,Sample Plaza,9100 Sample Plaza Dr,Houston,Retail,,Tenant,{y}-08-01,,\"$18,400.00\",\"$18,400.00\",{y}-08-20,,Lease value not in source",
        "SAMPLE Proposal - 12 Demo Way,Purchase,LOI,Sample Demo Way Lot,12 Demo Way,Houston,Land,,Buyer,,,,,,,LOI only; never went under contract",
        "SAMPLE Bad row - says closed without a date,Sale,Closed,Sample Missing Date,1 Missing Date Rd,Houston,Retail,,Seller,,\"$500,000\",,,,,",
    ]
    return "\n".join(rows) + "\n"


def offsets(today):
    """Relative dates so the demo is always current."""
    return {
        "d_effective": today - timedelta(days=20),
        "d_closing": today + timedelta(days=60),
        "d_amended_closing": today + timedelta(days=90),
        "d_unsigned_closing": today + timedelta(days=120),
        "c_signed_seller": today - timedelta(days=6),
        "c_signed_buyer": today - timedelta(days=4),
    }
