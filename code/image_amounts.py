"""
Amounts extracted by direct (human/AI) inspection of dataset/media/images/*.png.
Each image was matched to its financial_events.csv row via images.csv (related_event_id)
and the clearest authoritative total on the document was used:
 - image_01 (event_253, payslip, description "August 2019 net salary"): used "Net Pay"
 - image_02 (event_1442, rent receipt, "Outstanding rent balance"): used "Balance Due"
 - image_03 (event_1545, grocery bill): used "Net Amount" / "Cash Paid"
 - image_04 (event_1700, delivery app order, "Delivered grocery order"): used "Item Bill"
   (delivery-fee line is cropped/unreadable in the source image; not included)
 - image_05 (event_1786, telecom bill, "Outstanding telecom bill"): used "Amount due till" the event date
 - image_06 (event_3051, grocery tax invoice): used invoice "Total"
 - image_07 (event_3231, restaurant tax invoice): used computed "Total" (8528.10) over the
   rounded "Grand Total (RS): 8528" line
 - image_08 (event_4535, maintenance receipt, "Property maintenance invoice"): used "Total Amount Received"
 - image_09 (event_5170, water bill, "Water bill due"): used "Total Amount Received"
 - image_10 (event_6033, large grocery tax invoice): used invoice "Total"
 - image_11 (event_6859, hospital bill, "Hospital bill payable", status=scheduled/unpaid): used "Balance"
 - image_12 (event_7307, taxi receipt, "Taxi fare", currency USD): used "Total"
 - image_13 (event_7941, tote-bag order, "Tote bag order"): used "Total paid"
 - image_14 (event_9421, handwritten pharmacy bill, "Pharmacy purchase"): used the printed "TOTAL" field
 - image_15 (event_9806, airline invoice, "Airline ticket purchase"): used "Grand Total (Incl Taxes)"
 - image_16 (event_10521, EV charging invoice, "EV charging wallet payment"): used "Total"
   (cross-checked against message_?? MoneyHub notice referencing the same Charge Point 1110 /
   Krishnagiri session)

Keys are event_id -> (amount, currency-as-stated-in-financial_events-row, source image_id).
Currency here is only informational/cross-check; the authoritative currency for each event is
still whatever is in financial_events.csv (currency column), which is never blank.
"""

IMAGE_EVENT_AMOUNTS = {
    "event_253": 4365000.00,     # image_01, IDR
    "event_1442": 100000.00,     # image_02, INR
    "event_1545": 41272.00,      # image_03, INR
    "event_1700": 2854.00,       # image_04, INR
    "event_1786": 704.05,        # image_05, INR
    "event_3051": 1995.00,       # image_06, INR
    "event_3231": 8528.10,       # image_07, INR
    "event_4535": 15339.00,      # image_08, INR
    "event_5170": 723.00,        # image_09, INR
    "event_6033": 79679.26,      # image_10, INR
    "event_6859": 3650.00,       # image_11, INR
    "event_7307": 33.50,         # image_12, USD
    "event_7941": 2298.00,       # image_13, INR
    "event_9421": 4593.00,       # image_14, INR
    "event_9806": 9968.00,       # image_15, INR
    "event_10521": 393.22,       # image_16, INR
}
