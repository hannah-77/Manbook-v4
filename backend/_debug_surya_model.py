import torch
from surya.foundation import FoundationPredictor
from surya.layout import LayoutPredictor

if __name__ == "__main__":
    fp = FoundationPredictor()
    lp = LayoutPredictor(fp)
    print("Foundation model type:", type(fp.model) if hasattr(fp, "model") else "No model attr in fp")
    print("Layout model type:", type(lp.model) if hasattr(lp, "model") else "No model attr in lp")
