class ApplicationController < ActionController::Base
  def current_account
    @current_account ||= Account.first
  end
end
