"""Prompt templates for passage extraction and relevance scoring.

These templates use ChatML-style formatting for compatibility with
various LLM backends (local and API-based).
"""


class PassageExtractionPrompts:
    """Prompts for extracting relevant passages from documents."""

    @staticmethod
    def extract_relevant_passage(
        query: str,
        document_text: str,
        max_text_length: int = 500
    ) -> str:
        """Generate a prompt to extract the most relevant passage.

        Args:
            query: The user's search query
            document_text: The document to extract from
            max_text_length: Maximum characters for the extracted passage

        Returns:
            Formatted prompt string
        """
        return (
            f"<|system|>\n"
            f"You are a passage extraction assistant. Extract the most relevant "
            f"passage from the document that answers the query. "
            f"Keep the passage under {max_text_length} characters.\n"
            f"<|user|>\n"
            f"Query: {query}\n\n"
            f"Document:\n{document_text}\n\n"
            f"Extract the most relevant passage:"
        )


class RelevanceScoringPrompts:
    """Prompts for scoring document relevance to a query."""

    @staticmethod
    def score_relevance(
        query: str,
        document_excerpt: str
    ) -> str:
        """Generate a prompt to score relevance of a document excerpt.

        Args:
            query: The user's search query
            document_excerpt: The document excerpt to score

        Returns:
            Formatted prompt string
        """
        return (
            f"<|system|>\n"
            f"You are a relevance scoring assistant. Score how relevant the "
            f"document excerpt is to the query on a scale of 0-10. "
            f"Respond with only the number.\n"
            f"<|user|>\n"
            f"Query: {query}\n\n"
            f"Document excerpt: {document_excerpt}\n\n"
            f"Relevance score (0-10):"
        )
