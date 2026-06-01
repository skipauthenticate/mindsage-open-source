"""Integration tests for topic identification with real models.

These tests verify topic classification using the actual keyword matching
and optional embedding similarity classification.

Run with: pytest tests/test_topic_identification_integration.py -v
"""

import pytest
import os

# Add parent directory to path for imports
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_vector_store.topic_labeler import TopicLabeler, TopicResult, DEFAULT_TOPICS


class TestKeywordBasedTopicGeneration:
    """Tests for keyword-based topic classification."""

    @pytest.fixture
    def topic_labeler(self):
        """Create a TopicLabeler without embedding model (keyword-only)."""
        return TopicLabeler(verbose=False)

    def test_programming_document(self, topic_labeler):
        """Test that programming content is classified correctly."""
        text = """
        def quicksort(arr):
            if len(arr) <= 1:
                return arr
            pivot = arr[len(arr) // 2]
            left = [x for x in arr if x < pivot]
            middle = [x for x in arr if x == pivot]
            right = [x for x in arr if x > pivot]
            return quicksort(left) + middle + quicksort(right)
        """

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        assert len(result.topics) >= 1
        assert result.primary_topic is not None
        assert "programming" in result.topics, f"Expected 'programming' in {result.topics}"

    def test_database_document(self, topic_labeler):
        """Test that SQL/database content is classified correctly."""
        text = """
        SELECT users.name, orders.total
        FROM users
        INNER JOIN orders ON users.id = orders.user_id
        WHERE orders.created_at > '2024-01-01'
        GROUP BY users.name
        """

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        # SQL keywords should map to programming
        assert "programming" in result.topics, f"Expected 'programming' in {result.topics}"

    def test_technology_content(self, topic_labeler):
        """Test that technology content is classified correctly."""
        text = """
        The new smartphone features a faster processor and improved camera system.
        With software updates, the device performance has improved significantly.
        The laptop's hardware specifications include a high-resolution display.
        """

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        assert "technology" in result.topics, f"Expected 'technology' in {result.topics}"

    def test_health_content(self, topic_labeler):
        """Test that health/fitness content is classified correctly."""
        text = """
        My fitness routine includes a morning workout at the gym. I focus on
        proper nutrition and diet to maintain my wellness. Regular exercise
        helps with overall health and energy levels throughout the day.
        """

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        assert "health" in result.topics, f"Expected 'health' in {result.topics}"

    def test_work_content(self, topic_labeler):
        """Test that work-related content is classified correctly."""
        text = """
        Meeting with boss and colleagues at the office to discuss the project
        deadline. The career planning session covered job responsibilities.
        """

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        assert "work" in result.topics, f"Expected 'work' in {result.topics}"

    def test_finance_content(self, topic_labeler):
        """Test that finance content is classified correctly."""
        text = """
        Review the budget allocation and investment portfolio. Check the bank
        account balance and savings. Process the tax forms and credit report.
        """

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        assert "finance" in result.topics, f"Expected 'finance' in {result.topics}"

    def test_education_content(self, topic_labeler):
        """Test that education content is classified correctly."""
        text = """
        Studying for the university exam requires focus. The student attended
        the course at college. The teacher assigned homework and the learning
        materials for the school curriculum.
        """

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        assert "education" in result.topics, f"Expected 'education' in {result.topics}"

    def test_sports_content(self, topic_labeler):
        """Test that sports content is classified correctly."""
        text = """
        The basketball game was intense with the team scoring a touchdown
        wait no that's football. The NBA playoffs are exciting.
        """

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        assert "sports" in result.topics, f"Expected 'sports' in {result.topics}"

    def test_travel_content(self, topic_labeler):
        """Test that travel content is classified correctly."""
        text = """
        Booking a flight to the vacation destination. The hotel reservation
        is confirmed. Don't forget the passport for the international trip.
        """

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        assert "travel" in result.topics, f"Expected 'travel' in {result.topics}"

    def test_family_content(self, topic_labeler):
        """Test that family content is classified correctly."""
        text = """
        Family reunion with grandparents, parents, and siblings was wonderful.
        My brother and sister brought their kids. Mom and dad were so happy.
        """

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        assert "family" in result.topics, f"Expected 'family' in {result.topics}"

    def test_shopping_content(self, topic_labeler):
        """Test that shopping content is classified correctly."""
        text = """
        Went to the mall for shopping. Found great deals and discounts.
        Purchased new clothes and shoes. The checkout line was long.
        """

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        assert "shopping" in result.topics, f"Expected 'shopping' in {result.topics}"


class TestEdgeCases:
    """Edge case tests for topic classification."""

    @pytest.fixture
    def topic_labeler(self):
        return TopicLabeler(verbose=False)

    def test_empty_text(self, topic_labeler):
        """Test handling of empty text."""
        result = topic_labeler.generate_topics("", num_topics=3)

        assert result is not None
        assert result.primary_topic == "general"
        assert result.method == "empty_text"

    def test_very_short_text(self, topic_labeler):
        """Test handling of very short text."""
        result = topic_labeler.generate_topics("Python", num_topics=3)

        assert result is not None
        assert len(result.topics) >= 1

    def test_long_text_truncation(self, topic_labeler):
        """Test that very long text is handled (truncated)."""
        long_text = "Python programming " * 500  # ~9500 chars

        result = topic_labeler.generate_topics(long_text, num_topics=3)

        assert result is not None
        assert "programming" in result.topics

    def test_special_characters(self, topic_labeler):
        """Test handling of special characters."""
        text = "C++ programming with <templates> and &&references"

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        # Should still detect programming-related content
        assert "programming" in result.topics or "technology" in result.topics

    def test_unicode_text(self, topic_labeler):
        """Test handling of unicode text."""
        text = "Python programming tutorial 日本語テキスト"

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        assert "programming" in result.topics

    def test_ambiguous_content_gets_general(self, topic_labeler):
        """Test that ambiguous content gets reasonable classification."""
        text = "The weather today is sunny with a high of 75 degrees."

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        assert result.primary_topic in DEFAULT_TOPICS


class TestConfidenceAndMethods:
    """Tests for confidence scores and classification methods."""

    @pytest.fixture
    def topic_labeler(self):
        return TopicLabeler(verbose=False)

    def test_confidence_score_valid_range(self, topic_labeler):
        """Test that confidence scores are within valid range."""
        text = "Python programming tutorial for beginners"

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result.confidence >= 0.0
        assert result.confidence <= 1.0

    def test_high_confidence_for_specific_keywords(self, topic_labeler):
        """Test that specific keywords yield high confidence."""
        text = "quicksort algorithm implementation in Python with recursion"

        result = topic_labeler.generate_topics(text, num_topics=3)

        # Specific keywords like "quicksort", "algorithm", "python" should give high confidence
        assert result.confidence >= 0.6
        assert "programming" in result.topics

    def test_low_confidence_for_ambiguous_text(self, topic_labeler):
        """Test that ambiguous text yields lower confidence."""
        text = "Things happened today and stuff"

        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result.confidence < 0.6

    def test_method_field_set(self, topic_labeler):
        """Test that the method field is properly set."""
        text = "Database schema design for SQL tables."

        result = topic_labeler.generate_topics(text, num_topics=3)

        valid_methods = [
            "weighted_keyword_match", "embedding_similarity",
            "keyword_embedding_merged", "keyword_no_match",
            "embedding_low_match", "fallback", "empty_text"
        ]
        assert result.method in valid_methods, f"Unexpected method: {result.method}"

    def test_num_topics_respected(self, topic_labeler):
        """Test that num_topics parameter limits the result."""
        text = """
        This Python tutorial covers database queries with SQL,
        and also discusses health and fitness topics.
        """

        result = topic_labeler.generate_topics(text, num_topics=2)

        assert len(result.topics) <= 2


class TestAllDefaultTopics:
    """Test classification for all default topics."""

    @pytest.fixture
    def topic_labeler(self):
        return TopicLabeler(verbose=False)

    @pytest.mark.parametrize("text,expected_topic", [
        ("My fitness routine includes workout at the gym with proper nutrition and diet.", "health"),
        ("Review the budget and investment portfolio. Check bank savings and tax forms.", "finance"),
        ("Meeting with boss and colleagues at the office to discuss the project deadline.", "work"),
        ("My personal diary entry about my thoughts and feelings today.", "personal"),
        ("Going to a party with friends tonight for socializing and networking.", "social"),
        ("The lawyer reviewed the contract for the court lawsuit.", "legal"),
        ("Booking a flight and hotel for our vacation trip to the destination.", "travel"),
        ("Studying for the university exam, the student focuses on the course materials.", "education"),
        ("def fibonacci(n): return n if n <= 1 else fibonacci(n-1) + fibonacci(n-2)", "programming"),
        ("The basketball game went into overtime and the home team won the championship.", "sports"),
        ("The new smartphone has a faster processor and better camera.", "technology"),
        ("I bought a new dress and shoes at the mall during the sale.", "shopping"),
        ("Family reunion with grandparents and cousins was wonderful.", "family"),
    ])
    def test_topic_classification(self, topic_labeler, text, expected_topic):
        """Test that specific content is classified into the expected topic."""
        result = topic_labeler.generate_topics(text, num_topics=3)

        assert result is not None
        assert expected_topic in result.topics, \
            f"Expected '{expected_topic}' in {result.topics} for text: {text[:50]}..."


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
