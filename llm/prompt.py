from pydantic import BaseModel

from os import listdir
from os.path import getmtime, isfile, join


class PromptData(BaseModel):
    last_modify: float
    content: str


class PromptStore():
    store: dict[str, PromptData]

    def __init__(self) -> None:
        self.store = {}
        for filename in listdir("prompts"):
            if not filename.endswith(".md"):
                continue
            prompt_name = filename[:-3]
            self.load_prompt(prompt_name)

    def load_prompt(
        self,
        prompt_name: str,
        *,
        raise_if_not_exists: bool = True,
    ) -> None:
        path = join("prompts", f"{prompt_name}.md")
        if raise_if_not_exists and not isfile(path):
            raise FileNotFoundError(
                f"Prompt '{prompt_name}' not found at path: {path}")

        last_modify = getmtime(path)
        if prompt_name in self.store and self.store[prompt_name].last_modify >= last_modify:
            return

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.store[prompt_name] = PromptData(
            last_modify=last_modify,
            content=content,
        )

    def get_prompt(self, prompt_name: str) -> str:
        self.load_prompt(prompt_name, raise_if_not_exists=False)
        data = self.store.get(prompt_name)
        if data is None:
            raise ValueError(f"Prompt '{prompt_name}' not found")
        return data.content
