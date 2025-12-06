import numpy as np
import torch
import rasterio


class MockBiomasstersModel(torch.nn.Module):
    """Placeholder model to emulate BioMassters inference."""

    def __init__(self, in_channels=5):
        super().__init__()
        self.dummy_layer = torch.nn.Conv2d(in_channels, 1, kernel_size=1)

    def forward(self, x):
        return self.dummy_layer(x)


def load_model():
    model = MockBiomasstersModel()
    model.eval()
    return model


def predict_from_stack(stack: np.ndarray, reference_profile: dict, output_path):
    """
    Run biomass prediction on a stacked (C, H, W) array.
    Enforces CUDA execution to align with deployment target.
    """
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for biomass inference but is not available.")

    device = torch.device("cuda")
    model = load_model().to(device)

    tensor_input = torch.from_numpy(stack).unsqueeze(0).to(device)
    with torch.no_grad():
        prediction = model(tensor_input).squeeze().detach().cpu().numpy()

    profile = reference_profile.copy()
    profile.update(count=1, dtype="float32", driver="GTiff")
    with rasterio.open(str(output_path), "w", **profile) as dst:
        dst.write(prediction.astype(np.float32), 1)
