"""Next-round fixed replies (not wired in yet): product and beginner questions, plain definitions."""
import re
import pytest
from backend import smalltalk_more as sm

HIT = {"how are you different from chatgpt?": "vs_chatbots", "why not just use ChatGPT": "vs_chatbots",
       "who checks the numbers?": "who_checks", "can you be wrong?": "can_be_wrong", "how accurate are you": "can_be_wrong",
       "tell me one stock that is guaranteed to go up": "guaranteed", "is there a risk free investment": "guaranteed",
       "is my data stored?": "privacy", "do you save my questions": "privacy", "should i invest in openai": "private_co", "spacex stock price": "private_co",
       "como va apple hoy": "spanish", "cuál es el precio de las acciones de tesla": "spanish", "how do i start investing with $100?": "beginner", "im a beginner at stocks, help": "beginner",
       "what is a stock": "definition", "what is a dividend?": "definition", "what does market cap mean": "definition",
       "what is a 10-K": "definition", "what is P/E": "definition", "what's an ETF": "definition", "What is EPS?": "definition",
       "what is an index fund": "definition", "define ticker": "definition", "what is a bull and a bear market": "definition"}
MISS = ["What is EPS and what was Apple's in fiscal 2026?", "what is Apple's P/E", "What was Apple's revenue in fiscal 2026?",
        "is apple guaranteed to go up", "how do i start a position in nvidia", "how is the stock doing", "bear case for tesla",
        "what is the dividend yield of microsoft", "can apple be wrong about its guidance", "Does Apple pay a dividend?",
        "what is the 52-week high for nvidia", "why did the market fall", "hi", "should i buy tesla", "what is apple", "how is the data center business doing for nvidia", "is nvidia sharing more data on chips", "how is mercado libre doing"]


@pytest.mark.parametrize("q,kind", HIT.items())
def test_fixed_reply(q, kind):
    got = sm.reply(q)
    assert got and got[0] == kind
    assert not re.search(r"\d", got[1].replace("10-K", "")), "fixed replies carry no figures"


@pytest.mark.parametrize("q", MISS)
def test_company_and_figure_questions_still_reach_the_desk(q):
    assert sm.reply(q) is None
